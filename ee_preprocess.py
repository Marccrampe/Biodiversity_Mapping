import json  
import ee  
import numpy as np  
import requests 
from io import BytesIO  
from datetime import datetime, timedelta  
from google.cloud import storage  
import pandas as pd

def load_and_validate_geojson(bucket_name, geojson_path):
    """Charge et valide un fichier GeoJSON depuis un bucket Google Cloud Storage."""
    
    # ✅ Initialiser le client Google Cloud Storage
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(geojson_path)

    # ✅ Télécharger le fichier GeoJSON dans une variable
    geojson_data = blob.download_as_text()
    geojson = json.loads(geojson_data)

    # ✅ Extraire la géométrie du premier feature et la convertir en Geometry GEE
    return ee.Geometry.Polygon(geojson['features'][0]['geometry']['coordinates'])

def get_square_encompassing_polygon(polygon):
    """Generate a square that fully encompasses the given polygon."""
    bounds = polygon.bounds().coordinates().getInfo()[0]
    
    min_x = min([p[0] for p in bounds])
    max_x = max([p[0] for p in bounds])
    min_y = min([p[1] for p in bounds])
    max_y = max([p[1] for p in bounds])

    width = max_x - min_x
    height = max_y - min_y
    side = max(width, height)

    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2

    square_coords = [
        [center_x - side / 2, center_y - side / 2],
        [center_x + side / 2, center_y - side / 2],
        [center_x + side / 2, center_y + side / 2],
        [center_x - side / 2, center_y + side / 2],
        [center_x - side / 2, center_y - side / 2]  # close the polygon
    ]

    return ee.Geometry.Polygon([square_coords])



def create_composite(start_date, aoi, cloud_percentage=50):
    """Create a composite with lower cloud coverage."""
    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
    end_date_obj = start_date_obj + timedelta(days=90)
    end_date = end_date_obj.strftime("%Y-%m-%d")
    
    collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                  .filterBounds(aoi)
                  .filterDate(start_date, end_date)
                  .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', cloud_percentage)))
    
    sorted_collection = collection.sort('CLOUDY_PIXEL_PERCENTAGE')
    lowest_cloud_images = sorted_collection.limit(3)
    
    return lowest_cloud_images.median().toFloat()  # ✅ Ensure output is Float32
def compute_indices(image, indices=["NDVI", "NDWI", "SAVI", "EVI", "MSAVI", "BAI"]):
    """
    Computes multiple vegetation indices and returns only the selected ones.

    Parameters:
    - image: ee.Image (Sentinel-2 composite)
    - indices: list of indices to compute ["NDVI", "NDWI", "SAVI", "EVI", "MSAVI", "BAI"]

    Returns:
    - An ee.Image containing only the selected indices.
    """
    bands = []

    # NDVI = (NIR - Red) / (NIR + Red)
    if "NDVI" in indices:
        ndvi = image.normalizedDifference(["B8", "B4"]).rename("NDVI")
        bands.append(ndvi)

    # NDWI = (NIR - SWIR) / (NIR + SWIR)
    if "NDWI" in indices:
        ndwi = image.normalizedDifference(["B3", "B8"]).rename("NDWI")
        bands.append(ndwi)

    # SAVI = ((NIR - Red) / (NIR + Red + L)) * (1 + L)  (L = 0.5 by default)
    if "SAVI" in indices:
        savi = image.expression(
            "((NIR - RED) / (NIR + RED + 0.5)) * (1.5)", {
                "NIR": image.select("B8"),
                "RED": image.select("B4")
            }).rename("SAVI")
        bands.append(savi)

    # EVI = (G * (NIR - Red)) / (NIR + (C1 * Red) - (C2 * Blue) + L)
    if "EVI" in indices:
        evi = image.expression(
            "(G * (NIR - RED)) / (NIR + (C1 * RED) - (C2 * BLUE) + L)", {
                "NIR": image.select("B8"),
                "RED": image.select("B4"),
                "BLUE": image.select("B2"),
                "G": 2.5,  # Gain factor
                "C1": 6.0,  # Coefficient for RED
                "C2": 7.5,  # Coefficient for BLUE
                "L": 1.0  # Soil adjustment factor
            }).rename("EVI")
        bands.append(evi)

    # MSAVI = (2 * NIR + 1 - sqrt((2 * NIR + 1)^2 - 8 * (NIR - Red))) / 2
    if "MSAVI" in indices:
        msavi = image.expression(
            "(2 * NIR + 1 - sqrt((2 * NIR + 1) ** 2 - 8 * (NIR - RED))) / 2", {
                "NIR": image.select("B8"),
                "RED": image.select("B4")
            }).rename("MSAVI")
        bands.append(msavi)

    # BAI = (B - NIR) / (B + NIR)  (custom formula)
    if "BAI" in indices:
        bai = image.expression(
            "(BLUE - NIR) / (BLUE + NIR)", {
                "BLUE": image.select("B2"),
                "NIR": image.select("B8")
            }).rename("BAI")
        bands.append(bai)

    # Combine all selected indices into a single image
    return ee.Image(bands).toFloat()

    

def create_data_cube(aoi, start_date, end_date, period="10D", indices=["NDVI"]):
    """
    Creates a time-series data cube containing selected indices and/or Sentinel-2 bands.

    Parameters:
    - aoi: ee.Geometry, area of interest
    - start_date: str, start date ("YYYY-MM-DD")
    - end_date: str, end date ("YYYY-MM-DD")
    - period: str, acquisition frequency ("10D", "1M" for monthly)
    - indices: list of indices and/or "S2" to include raw Sentinel-2 bands

    Returns:
    - An ee.ImageCollection representing the temporal data cube.
    """
    # Convert date strings to datetime objects
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    # Generate a list of dates at the chosen frequency
    dates = []
    current_date = start
    while current_date <= end:
        dates.append(current_date.strftime("%Y-%m-%d"))
        if "D" in period:
            days = int(period.replace("D", ""))
            current_date += timedelta(days=days)
        elif "M" in period:
            current_date += timedelta(days=30)  # Approximate monthly interval

    # Build the data cube by computing indices and/or including Sentinel-2 bands
    cube = []
    for date in dates:
        composite = create_composite(date, aoi)  # Generate composite for the given date

        # If "S2" is in the indices list, include raw Sentinel-2 bands
        if "S2" in indices:
            s2_bands = composite.select(["B2", "B3", "B4", "B8", "B11", "B12"])  # Key S2 bands
        else:
            s2_bands = None

        # Compute vegetation indices if selected
        selected_indices = [i for i in indices if i != "S2"]
        if selected_indices:
            index_image = compute_indices(composite, selected_indices)
        else:
            index_image = None

        # Merge S2 bands and indices if both are selected
        if s2_bands and index_image:
            final_image = s2_bands.addBands(index_image)
        elif s2_bands:
            final_image = s2_bands
        elif index_image:
            final_image = index_image
        else:
            final_image = None  # Should never happen

        if final_image:
            cube.append(final_image)

    return ee.ImageCollection(cube)


def get_dlc_mask_numpy(aoi, start_date, end_date, period="10D"):
    """
    Retrieves land cover masks (DLC) as NumPy arrays for each date.
    Keeps only classes relevant for biodiversity (trees, grass, crops, shrubs, etc.).
    Excludes built areas and bare ground. Falls back to ESA WorldCover if DW unavailable.
    """
    masks = {}
    dates = pd.date_range(start=start_date, end=end_date, freq=period)

    # Load ESA fallback (exclude built + bare)
    esa_mask_numeric = None
    try:
        esa_image = ee.ImageCollection("ESA/WorldCover/v200").first().clip(aoi)
        exclude_classes = [50, 60]  # 50 = Urban, 60 = Bare Sparse Vegetation
        mask = ee.Image(1)
        for cls in exclude_classes:
            mask = mask.multiply(esa_image.select("Map").neq(cls))
        esa_mask_resampled = mask.reproject(crs='EPSG:4326', scale=10)

        url_esa = esa_mask_resampled.getDownloadURL({
            'scale': 10,
            'region': aoi,
            'format': 'NPY'
        })
        r = requests.get(url_esa, stream=True)
        if r.status_code == 200:
            esa_np = np.load(BytesIO(r.content))
            esa_mask_numeric = esa_np[esa_np.dtype.names[0]] if esa_np.dtype.names else esa_np
            print("✅ ESA mask loaded.")
        else:
            print(f"❌ ESA mask HTTP error: {r.status_code}")
    except Exception as e:
        print(f"❌ ESA mask error: {e}")

    # Loop over dates
    for date in dates:
        date_str = date.strftime("%Y-%m-%d")
        print(f"📅 Processing mask for {date_str}")
        mask_np = None

        try:
            dw_image = ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1") \
                .filterBounds(aoi) \
                .filterDate(date_str, (date + timedelta(days=30)).strftime("%Y-%m-%d")) \
                .first()

            if dw_image:
                dw_image = dw_image.clip(aoi)

                # ❌ Only exclude built area and bare ground (6 & 7)
                exclude = [6, 7]
                dw_mask = dw_image.select("label").neq(ee.Image.constant(exclude)).reduce(ee.Reducer.min())
                binary_mask = dw_mask.eq(1).reproject(crs='EPSG:4326', scale=10)

                url = binary_mask.getDownloadURL({
                    'scale': 10,
                    'region': aoi,
                    'format': 'NPY'
                })
                r = requests.get(url, stream=True)
                if r.status_code == 200:
                    dlc_np = np.load(BytesIO(r.content))
                    mask_np = dlc_np[dlc_np.dtype.names[0]] if dlc_np.dtype.names else dlc_np
                    print(f"✅ DW mask loaded for {date_str}")
                else:
                    print(f"❌ DW HTTP error for {date_str}: {r.status_code}")
            else:
                print(f"⚠️ No DW image for {date_str}")

        except Exception as e:
            print(f"❌ DW error for {date_str}: {e}")

        # Fallback to ESA if needed
        if mask_np is None or np.all(mask_np == 0):
            print(f"🟡 Using ESA fallback for {date_str}")
            mask_np = esa_mask_numeric

        if mask_np is not None:
            masks[date_str] = mask_np
        else:
            print(f"❌ No mask available for {date_str}")

    return masks
