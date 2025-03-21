import os
import sys
import ee
import json
import time
import rasterio
import numpy as np
import pandas as pd
import google.auth
from datetime import datetime, timedelta
from google.cloud import storage

# === Custom Modules ===
from ee_preprocess import (
    load_and_validate_geojson,
    get_square_encompassing_polygon,
    create_data_cube,
    get_dlc_mask_numpy
)
from rasterdiv_preprocess import (
    load_raster,
    raster_to_numpy,
    compute_shannon_entropy,
    compute_renyi_entropy,
    compute_rao_q,
    compute_3d_window_entropy_map,
    compute_pixelwise_temporal_entropy
)
from ee_logistic import (
    get_args,
    initialize_gee,
    export_image_to_gcs,
    move_image_after_analysis,
    save_as_geotiff
)

# === Load Arguments ===
args = get_args()
selected_index = args.index
entropy_measure = args.entropy
window_size = args.window_size

start_date, end_date = args.start, args.end
date_range = (start_date, end_date)
frequency = args.frequency
geojson_path = args.geojson
bucket_name = args.bucket
input_folder = args.input_folder
entropy_folder = args.entropy_folder

# === Extract AOI name from file path ===
aoi_name = os.path.splitext(os.path.basename(geojson_path))[0]

# === Initialize EE & GCS ===
credentials, project = google.auth.default()
storage_client = storage.Client(credentials=credentials, project=project)
ee.Initialize(project='canopy-height-model-00')

# === 1. Load AOI ===
aoi = load_and_validate_geojson(bucket_name, geojson_path)
geometry = get_square_encompassing_polygon(aoi)

# === 2. Create NDVI DataCube ===
data_cube = create_data_cube(geometry, start_date, end_date, period=frequency, indices=[selected_index])

# === 3. Generate DLC Masks ===
dlc_masks = get_dlc_mask_numpy(geometry, start_date, end_date, period=frequency)

# === 4. Export NDVI Cube ===
datacube_filename = f"{selected_index}_datacube_{start_date}_{end_date}"
export_image_to_gcs(data_cube.toBands(), input_folder, datacube_filename, bucket_name, geometry)
print(f"✅ Exported DataCube as {datacube_filename}")

# === 5. Check GCS Export ===
print("📂 Checking for DataCube TIFF in Google Cloud Storage...")
bucket = storage_client.bucket(bucket_name)
blobs = bucket.list_blobs(prefix=f"{input_folder}/")
image_names = [blob.name for blob in blobs if blob.name.endswith(".tif")]

if not image_names:
    print(f"❌ No DataCube found in {input_folder}. Exiting...")
    sys.exit(1)

print(f"✅ Found {len(image_names)} TIFF files. Processing entropy...")

# === 6. Download Cube Locally ===
datacube_path = f"gs://{bucket_name}/{input_folder}/{datacube_filename}.tif"
local_tiff = f"/tmp/{datacube_filename}.tif"
blob = bucket.blob(f"{input_folder}/{datacube_filename}.tif")
blob.download_to_filename(local_tiff)
print(f"✅ Downloaded DataCube to {local_tiff}")

# === 7. Per-Date Entropy Processing ===
entropy_results = []
dates = pd.date_range(start=start_date, end=end_date, freq=frequency)

with rasterio.open(local_tiff) as src:
    num_bands = src.count
    meta = src.meta.copy()
    for i in range(num_bands):
        date_str = dates[i].strftime("%Y-%m-%d")
        print(f"📅 Processing time step {i + 1} - {date_str}")

        timestep_array = src.read(i + 1)
        timestep_array_discrete = np.round(timestep_array * 100).astype(int)

        if date_str in dlc_masks:
            dlc_mask = np.array(dlc_masks[date_str], dtype=np.float32)
            timestep_array_discrete[dlc_mask == 0] = 0
            print(f"✅ Applied DLC mask for {date_str}")
        else:
            print(f"⚠️ No DLC mask for {date_str} – skipping masking.")

        if entropy_measure == "shannon":
            entropy_array = compute_shannon_entropy(timestep_array_discrete, window_size)
        elif entropy_measure == "renyi_0":
            entropy_array = compute_renyi_entropy(timestep_array_discrete, alpha=0, window_size=window_size)
        elif entropy_measure == "renyi_2":
            entropy_array = compute_renyi_entropy(timestep_array_discrete, alpha=2, window_size=window_size)
        elif entropy_measure == "rao_q":
            entropy_array = compute_rao_q(timestep_array_discrete, window_size)
        else:
            raise ValueError(f"❌ Invalid entropy measure: {entropy_measure}")

        entropy_results.append(entropy_array)

        if i == 0:
            index_cube = [timestep_array_discrete]
        else:
            index_cube.append(timestep_array_discrete)

# === 8. Compute Extra Entropy Layers ===
cube = np.stack(index_cube, axis=0).astype(np.float32)  # shape = (T, H, W)

print("🧠 Computing 3D window-based entropy...")
entropy_3d = compute_3d_window_entropy_map(
    cube, spatial_window=window_size, entropy_type=entropy_measure
)

print("🧠 Computing temporal entropy...")
temporal_entropy_map = compute_pixelwise_temporal_entropy(cube)

# === 9. Save All Entropy Bands to TIFF ===
entropy_filename = f"{entropy_measure}_{selected_index}_{aoi_name}_{start_date}_{end_date}_w{window_size}.tif"
entropy_tiff_path = f"/tmp/{entropy_filename}"

with rasterio.open(
    entropy_tiff_path, "w",
    driver="GTiff",
    height=entropy_results[0].shape[0],
    width=entropy_results[0].shape[1],
    count=num_bands + 2,
    dtype=rasterio.float32,
    crs=meta["crs"],
    transform=meta["transform"]
) as dst:
    for i, (band, date) in enumerate(zip(entropy_results, dates)):
        dst.write(band, i + 1)
        dst.set_band_description(i + 1, f"{entropy_measure}_{date.strftime('%Y-%m-%d')}")

    dst.write(temporal_entropy_map, num_bands + 1)
    dst.set_band_description(num_bands + 1, f"{entropy_measure}_temporal_variability")

    dst.write(entropy_3d, num_bands + 2)
    dst.set_band_description(num_bands + 2, f"{entropy_measure}_3D_window_entropy")

print(f"✅ Saved Entropy DataCube as {entropy_tiff_path}")

# === 10. Upload to GCS ===
blob = bucket.blob(f"{entropy_folder}/{entropy_filename}")
blob.upload_from_filename(entropy_tiff_path)
print(f"✅ Uploaded to gs://{bucket_name}/{entropy_folder}/")

# === 11. Move Raw NDVI Cube to Archive ===
datacube_move = f"{datacube_filename}.tif"
move_image_after_analysis(datacube_move, input_folder, entropy_folder, bucket_name)

# === 12. Cleanup ===
os.remove(entropy_tiff_path)
print("🎉 Entropy Processing Complete!")