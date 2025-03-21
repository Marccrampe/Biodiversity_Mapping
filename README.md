# 🛰️ Sentinel-2 Entropy Analysis Pipeline

This pipeline computes **spatial**, **temporal**, and **spatio-temporal entropy** maps from a Sentinel-2 vegetation index (NDVI, SAVI, or EVI). It combines Google Earth Engine (GEE) and local Python processing for a scalable and modular entropy-based analysis of ecosystem dynamics.

---

## 📦 Outputs

The pipeline generates a single multi-band GeoTIFF that includes:

1. ✅ **Per-date spatial entropy**: Shannon / Rényi / Rao-Q entropy computed per date using a spatial sliding window  
2. ✅ **Pixelwise temporal variability**: entropy computed **over time** for each pixel  
3. ✅ **3D spatio-temporal entropy**: entropy computed from a local cube (T × W × W) per pixel  

🗂️ **TIFF file is named automatically** for traceability:

```
{entropy}_{index}_{AOI}_{start}_{end}_w{window_size}.tif
```

> Example: `shannon_NDVI_AoI_France_2023-06-01_2023-06-30_w7.tif`

---

## 📈 What is Computed?

### 1. Spatial Entropy per Time Step
For each image in the time series, the selected entropy is computed over a W×W sliding window:
- **Shannon**: classic entropy measuring local diversity
- **Rényi (α=0,2)**: generalized entropy family (α=2 favors dominant classes)
- **Rao Q**: integrates pairwise distances between pixel values

### 2. Pixelwise Temporal Entropy
For each pixel across all dates:
- Shannon entropy of the temporal sequence
- Measures how stable/dynamic a pixel is through time

🟢 **Use case**: detect dynamic land uses like crops or urban edges

### 3. 3D Spatio-Temporal Entropy
For each pixel, a local 3D window is extracted:
- Shape: (T, W, W)
- Flattened, then entropy is computed over values

🧠 This reveals **complexity in space and time**, great for identifying ecotones or transitional habitats.

Supports:
- `shannon`
- `renyi_0`, `renyi_2`
- `rao_q`

---

## 🧼 Land Cover Masking (Vegetation Only)

Before entropy computation, each time step is masked to exclude non-natural land cover:

- ✅ **Primary mask**: [Dynamic World](https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_DYNAMICWORLD_V1)
- 🟡 **Fallback**: [ESA WorldCover 2020](https://developers.google.com/earth-engine/datasets/catalog/ESA_WorldCover_v200)

**Masked classes include:**
- Water (0)
- Built-up (5)
- Snow/Ice (6)
- Barren (7)
- Impervious areas (8)

Only natural surfaces (forests, shrubs, crops, grasslands) are retained.

---

## 🧪 Parameters

| Flag              | Description                                          | Example              |
|-------------------|------------------------------------------------------|----------------------|
| `--index`         | Index to compute (NDVI, SAVI, EVI)                   | `--index NDVI`       |
| `--entropy`       | Type of entropy to use (`shannon`, `renyi_0`, `renyi_2`, `rao_q`) | `--entropy shannon` |
| `--start`         | Start date                                           | `--start 2023-06-01` |
| `--end`           | End date                                             | `--end 2023-06-30`   |
| `--frequency`     | Temporal step (e.g. 10D, 1M)                         | `--frequency 10D`    |
| `--window_size`   | Size of spatial window (must be odd)                 | `--window_size 7`    |
| `--geojson`       | Path to AOI file                                     | `--geojson AOI/AoI_France.json` |
| `--bucket`        | GCS bucket name                                      | `--bucket my-bucket` |
| `--input_folder`  | Subfolder for input cube                             | `--input_folder rasterdiv_map` |
| `--entropy_folder`| Subfolder for output entropy files                   | `--entropy_folder entropy`     |

---

## 💻 Example Command

```bash
python entropy_pipeline.py \
  --index NDVI \
  --entropy shannon \
  --start 2023-06-01 \
  --end 2023-06-30 \
  --frequency 10D \
  --window_size 7 \
  --geojson AOI/AoI_France.json \
  --bucket gchm-predictions-test \
  --input_folder rasterdiv_map \
  --entropy_folder entropy
```

---

## 🌍 Requirements

- Python 3.8+
- Google Earth Engine Python API
- `rasterio`, `numpy`, `pandas`, `scipy`, `google-cloud-storage`

✅ Ensure that Earth Engine and GCS credentials are correctly configured.

---

## 📁 Project Structure

```
entropy_pipeline.py         # Main pipeline
parser.py                   # Argument parser
ee_preprocess.py            # GEE-related functions
rasterdiv_preprocess.py     # Entropy computation functions
AOI/                        # Folder with AOI GeoJSON files
```

---

## 🤝 Contributions

Feel free to open an issue or submit a PR to improve entropy models, extend entropy measures, or optimize 3D performance.

---

## 👋 Authors

Developed by Marc CRAMPE, 2024  
