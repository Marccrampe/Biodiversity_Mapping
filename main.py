import os
import sys
import json
import time
import ee
import rasterio
import numpy as np
import google.auth
from datetime import datetime, timedelta
from google.cloud import storage

# ✅ Import custom functions
from ee_preprocess import load_and_validate_geojson,create_composite, get_dlc_mask,get_square_encompassing_polygon,compute_indices,create_data_cube
from rasterdiv_preprocess import load_raster,raster_to_numpy
from ee_logistic import initialize_gee,export_image_to_gcs,move_image_after_analysis

# ✅ Set up Google Cloud Storage and Earth Engine
credentials, project = google.auth.default()
storage_client = storage.Client(credentials=credentials, project=project)
ee.Initialize(project='canopy-height-model-00')

# ✅ User-defined parameters
bucket_name = "gchm-predictions-test"  # Update this
geojson_path = "AOI/AoI_Florida.json"  # Update this
date_range = ("2023-06-01", "2023-06-30")  # Start and end dates
frequency = "10D"  # Frequency of images (e.g., every 10 days)
indices = ["S2", "NDVI", "NDWI"]  # Indices to compute
input_folder = "rasterdiv_data"  # Where exported images are stored
output_folder = "rasterdiv_map"  # Where processed images are moved

# ✅ 1. Load AOI from GeoJSON stored in GCS
aoi = load_and_validate_geojson(bucket_name,geojson_path)

# ✅ 2. Generate bounding box geometry
geometry = get_square_encompassing_polygon(aoi)

# ✅ 3. Retrieve DLC masks (Dynamic World & ESA WorldCover)
dlc_masks = get_dlc_mask(geometry, [date_range[0], date_range[1]])

# ✅ 4. Create a time-series data cube with selected indices
data_cube = create_data_cube(geometry, date_range[0], date_range[1], period=frequency, indices=indices)

# ✅ 5. Export each time step of the data cube to GCS
image_list = data_cube.toList(data_cube.size())  # Keep this as an EE list

for i in range(data_cube.size().getInfo()):  # Get number of images
    date = (datetime.strptime(date_range[0], "%Y-%m-%d") + timedelta(days=i * 10)).strftime("%Y-%m-%d")
    file_name = f"{geojson_path.replace('.json', '').replace('/', '_').replace(' ', '_')}_{date}"
    
    # ✅ Retrieve the ee.Image correctly
    image = ee.Image(image_list.get(i))  # Get the image from the list
    
    export_image_to_gcs(image,input_folder, file_name, bucket_name, geometry)
    print(f"✅ Image for {date} exported to gs://{bucket_name}/Rasterdiv_data/{file_name}.tif")


# ✅ 6. Verify exported images in GCS
bucket = storage_client.bucket(bucket_name)
blobs = bucket.list_blobs(prefix=f"{input_folder}/")
image_names = [blob.name.replace(f"{input_folder}/", "") for blob in blobs if blob.name.endswith(".tif")]


# ✅ 7. Process each exported Sentinel-2 image
for image_name in image_names:
    print(f"🔄 Downloading and processing: {image_name}")

    # ⬇️ Load the raster from GCS as a NumPy array
    raster_array, meta = load_raster(f"gs://{bucket_name}/{input_folder}/{image_name}")
    numpy_array = raster_to_numpy(raster_array, meta, set_nodata_to_nan=True)

    # Example: Print basic stats
    print(f"📊 Raster {image_name} - Shape: {numpy_array.shape}, Min: {np.nanmin(numpy_array)}, Max: {np.nanmax(numpy_array)}")

    # ✅ Move processed images to output folder
    move_image_after_analysis(image_name, input_folder, output_folder, bucket_name)

print("🎉 Processing complete!")
