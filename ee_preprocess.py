import json  
import ee  
import numpy as np  
import requests 
from io import BytesIO  
from datetime import datetime, timedelta  
from google.cloud import storage  


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

    
def compute_indices(image, indices=["NDVI", "NDWI", "SAVI", "BAI"]):
    """
    Computes multiple vegetation indices and returns only the selected ones.

    Parameters:
    - image: ee.Image (Sentinel-2 composite)
    - indices: list of indices to compute ["NDVI", "NDWI", "SAVI", "BAI", etc.]

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


    
        
    # Function to get the DLC mask from Dynamic World (GOOGLE/DYNAMICWORLD/V1)
def get_dlc_mask(aoi, date_array):
    """
    For each date in date_array, tries to get the mask from Dynamic World.
    If no DW mask is generated (or if it is empty), we use a static mask from ESA WorldCover.
    The returned mask is a NumPy array (unstructured).

    Parameters:
      - aoi: area of interest (an ee.Geometry)
      - date_array: list of dates (format "YYYY-MM-DD")

    Returns:
      - Dictionary mapping each date to a NumPy array representing the mask
    """

    masks = {}  # Dictionary to store masks for each date

    # --- Load ESA WorldCover mask once ---
    try:
        # Load ESA WorldCover v200 (this is a collection, so we take the first image)
        esa_image = ee.ImageCollection("ESA/WorldCover/v200").first().clip(aoi)
        # Define excluded classes for ESA (e.g., 50, 60, 70, 80)
        exclude_classes_esa = [50, 60, 70, 80]

        # Create a binary mask: pixel value is 1 if "Map" is not in excluded classes
        mask_product = ee.Image(1)
        for cls in exclude_classes_esa:
            mask_product = mask_product.multiply(esa_image.select("Map").neq(cls))

        esa_mask_resampled = mask_product.reproject(crs='EPSG:4326', scale=10)

        # Get the download URL for the ESA mask in NPY format
        url_esa = esa_mask_resampled.getDownloadURL({
            'scale': 10,
            'region': aoi,
            'format': 'NPY'
        })
        response_esa = requests.get(url_esa, stream=True)
        if response_esa.status_code == 200:
            mask_array_esa = np.load(BytesIO(response_esa.content))
            if mask_array_esa.dtype.names is not None:
                field = mask_array_esa.dtype.names[0]
                esa_mask_numeric = mask_array_esa[field]
            else:
                esa_mask_numeric = mask_array_esa
            print("ESA mask successfully loaded.")
        else:
            print("HTTP error", response_esa.status_code, "while downloading ESA mask.")
            esa_mask_numeric = None
    except Exception as e:
        print("Exception while loading ESA mask:", e)
        esa_mask_numeric = None

    # --- Process each date ---
    for start_date in date_array:
        mask_numeric = None  # Final mask for this date
        # Compute the 90-day period from start_date
        try:
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
            end_date_obj = start_date_obj + timedelta(days=90)
            end_date = end_date_obj.strftime("%Y-%m-%d")
        except Exception as e:
            print(f"[{start_date}] Error computing date range: {e}")
            continue

        # 1. Attempt to get Dynamic World mask
        try:
            dlc_collection = ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
            dlc_filtered = dlc_collection.filterBounds(aoi).filterDate(start_date, end_date).first()
            if dlc_filtered is not None:
                dlc_filtered = dlc_filtered.clip(aoi)
                # Define excluded classes for DW (e.g., 0, 5, 6, 7, 8)
                exclude_classes = [0, 5, 6, 7, 8]
                # Create a binary mask: pixel is 1 if it does not belong to excluded classes
                dlc_mask = dlc_filtered.select("label").neq(ee.Image.constant(exclude_classes)).reduce(ee.Reducer.min())
                dlc_mask_binary = dlc_mask.eq(1)
                dlc_mask_resampled = dlc_mask_binary.reproject(crs='EPSG:4326', scale=10)

                url_dw = dlc_mask_resampled.getDownloadURL({
                    'scale': 10,
                    'region': aoi,
                    'format': 'NPY'
                })
                response_dw = requests.get(url_dw, stream=True)
                if response_dw.status_code == 200:
                    mask_array = np.load(BytesIO(response_dw.content))
                    if mask_array.dtype.names is not None:
                        field = mask_array.dtype.names[0]
                        mask_numeric = mask_array[field]
                    else:
                        mask_numeric = mask_array
                    print(f"[{start_date}] DW mask generated.")
                else:
                    print(f"[{start_date}] HTTP error {response_dw.status_code} for DW.")
            else:
                print(f"[{start_date}] No DW image found.")
        except Exception as e:
            print(f"[{start_date}] Exception processing DW: {e}")

        # 2. If DW mask is unavailable or empty, use the preloaded ESA mask
        if mask_numeric is None or np.all(mask_numeric == 0):
            print(f"[{start_date}] Using ESA static mask.")
            mask_numeric = esa_mask_numeric

        if mask_numeric is not None:
            masks[start_date] = mask_numeric
        else:
            print(f"[{start_date}] No mask could be generated.")

    return masks