import os
import rasterio
import numpy as np
import logging
from google.cloud import storage
from scipy.stats import entropy
from skimage.util.shape import view_as_windows
from scipy.spatial.distance import pdist, squareform
from scipy.ndimage import generic_filter

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


# === 2. Shannon Entropy Function ===
def compute_shannon_entropy(image, window_size=7):
    """
    Computes Shannon entropy using a sliding window.

    Parameters:
    - image: np.array, input raster
    - window_size: int, size of the sliding window

    Returns:
    - entropy_raster: np.array, Shannon entropy map
    """
    def shannon_entropy(window):
        unique, counts = np.unique(window, return_counts=True)
        probabilities = counts / counts.sum()
        return entropy(probabilities, base=2) if len(probabilities) > 1 else 0

    return generic_filter(image, shannon_entropy, size=window_size, mode='reflect')

# === 3. Rényi Entropy Function (Includes Shannon for α=1) ===
def compute_renyi_entropy(image, alpha=2, window_size=7):
    """
    Computes Rényi entropy using a sliding window.

    If alpha = 1, the function defaults to Shannon entropy.

    Parameters:
    - image: np.array, input raster
    - alpha: float, order parameter of Rényi entropy (α > 0, α ≠ 1)
    - window_size: int, size of the sliding window

    Returns:
    - entropy_raster: np.array, Rényi entropy map
    """
    # if alpha == 1:
    #     return compute_shannon_entropy(image, window_size)

    def renyi_entropy(window):
        unique, counts = np.unique(window, return_counts=True)
        probabilities = counts / counts.sum()
        return (1 / (1 - alpha)) * np.log(np.sum(probabilities ** alpha)) if len(probabilities) > 1 else 0

    return generic_filter(image, renyi_entropy, size=window_size, mode='reflect')


# === 4. Rao’s Quadratic Entropy Function (Rao Q) ===
def compute_rao_q(image, window_size=7):
    """
    Computes Rao’s quadratic entropy using a sliding window.

    Parameters:
    - image: np.array, input raster
    - window_size: int, size of the sliding window

    Returns:
    - rao_q_raster: np.array, Rao Q entropy map
    """
    def rao_q(window):
        unique, counts = np.unique(window, return_counts=True)
        probabilities = counts / counts.sum()
        distances = squareform(pdist(unique[:, None]))  # Distance matrix between unique values
        return np.sum(probabilities[:, None] * probabilities[None, :] * distances) if len(probabilities) > 1 else 0

    return generic_filter(image, rao_q, size=window_size, mode='reflect')

### 3D entropies function , so we have an entropy map anyalizing spatial-temporal species variation

def compute_3d_window_entropy_map(cube, spatial_window=3, entropy_type="shannon", alpha=2):
    """
    Computes a 2D map of entropy per pixel, based on a 3D window (T x WxW) around each pixel.

    Parameters:
        - cube: np.array of shape (T, H, W)
        - spatial_window: int (must be odd)
        - entropy_type: "shannon", "renyi_0", "renyi_2", or "rao_q"
        - alpha: float (used only for renyi variants)

    Returns:
        - 2D entropy map of shape (H, W)
    """
    from scipy.stats import entropy as shannon_entropy
    from scipy.spatial.distance import pdist, squareform

    T, H, W = cube.shape
    pad = spatial_window // 2

    padded = np.pad(cube, ((0, 0), (pad, pad), (pad, pad)), mode='reflect')
    result = np.zeros((H, W), dtype=np.float32)

    for i in range(H):
        for j in range(W):
            window = padded[:, i:i+spatial_window, j:j+spatial_window]
            values = window.flatten()
            unique, counts = np.unique(values, return_counts=True)
            probs = counts / counts.sum()

            if len(probs) <= 1:
                result[i, j] = 0
                continue

            if entropy_type == "shannon":
                result[i, j] = shannon_entropy(probs, base=2)
            elif entropy_type == "renyi_0":
                result[i, j] = (1 / (1 - 0)) * np.log(np.sum(probs ** 0))  # will raise div by 0 if not caught
            elif entropy_type == "renyi_2":
                result[i, j] = (1 / (1 - 2)) * np.log(np.sum(probs ** 2))
            elif entropy_type == "rao_q":
                distances = squareform(pdist(unique[:, None]))
                result[i, j] = np.sum(probs[:, None] * probs[None, :] * distances)
            else:
                raise ValueError("Invalid entropy type.")

    return result



###Compute temporal entropy at each pixel location (H x W) over time (T).

def compute_pixelwise_temporal_entropy(cube):
    """
    Compute temporal entropy at each pixel location (H x W) over time (T).

    Parameters:
        cube: np.array of shape (T, H, W)

    Returns:
        2D array (H x W) of entropy values
    """
    T, H, W = cube.shape
    result = np.zeros((H, W), dtype=np.float32)

    for i in range(H):
        for j in range(W):
            time_series = cube[:, i, j]
            values, counts = np.unique(time_series, return_counts=True)
            probs = counts / counts.sum()
            result[i, j] = entropy(probs, base=2) if len(probs) > 1 else 0

    return result