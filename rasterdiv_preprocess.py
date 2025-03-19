import os
import rasterio
import numpy as np
import logging
from google.cloud import storage

def load_raster(gcs_path):
    """
    Loads a raster from Google Cloud Storage (GCS) into Python.

    Parameters:
    - gcs_path: str, full GCS path (e.g., "gs://your-bucket-name/DATASET_GEE_TIF/image.tif")

    Returns:
    - raster_array: NumPy array of the raster
    - meta: Metadata of the raster (projection, transform, etc.)
    """
    # Extract bucket name and blob name from GCS path
    gcs_path = gcs_path.replace("gs://", "")  # Remove "gs://" prefix
    bucket_name, blob_name = gcs_path.split("/", 1)

    # Create a local temporary file path
    local_path = f"/tmp/{blob_name.split('/')[-1]}"

    # Initialize GCS client and download the file
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.download_to_filename(local_path)

    print(f"✅ Raster downloaded from GCS: {local_path}")

    # Open the raster with rasterio
    with rasterio.open(local_path) as src:
        raster_array = src.read()  # Read all bands as a NumPy array
        meta = src.meta  # Get metadata

    return raster_array, meta
    

def raster_to_numpy(raster_array, meta, set_nodata_to_nan=True):
    """
    Converts a raster dataset to a NumPy array with optional NoData handling.

    Parameters:
    - raster_array: NumPy array of the raster
    - meta: Metadata dictionary (contains NoData value)
    - set_nodata_to_nan: bool, whether to replace NoData values with NaN

    Returns:
    - numpy_array: Processed NumPy array
    """
    # Get NoData value from metadata
    nodata_value = meta.get("nodata", None)

    # Convert to float to handle NaN values properly
    numpy_array = raster_array.astype(float)

    # Replace NoData values with NaN (if applicable)
    if set_nodata_to_nan and nodata_value is not None:
        numpy_array[numpy_array == nodata_value] = np.nan

    return numpy_array
