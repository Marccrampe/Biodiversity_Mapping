# 🌍 GEE & Google Cloud Storage Processing Package

This repository contains a set of functions for processing **Google Earth Engine (GEE)** data and exporting raster images to **Google Cloud Storage (GCS)**.  
The package includes functions for **retrieving Sentinel-2 composites**, **computing vegetation indices**, **loading rasters**, and **moving processed images**.

---

## 📦 **Package Structure**

│── main.py # Example script for running the package 

│── ee_preprocess.py # Functions for GEE processing & data cube creation

│── rasterdiv_preprocess.py # Functions for loading & processing raster images

│── ee_logistic.py # Functions for exporting & managing images on GCS 


│── requirements.txt # Required Python dependencies 

│── README.md # Documentation 
#

## ⚡ **Installation**
Before running the script, install the necessary dependencies:
```bash
pip install -r requirements.txt
```
🔥 How to Use
An example script is provided in main.py that demonstrates how to:

✅ Load an AOI (GeoJSON) from GCS
✅ Create a Sentinel-2 composite & vegetation indices
✅ Export images to Google Cloud Storage
✅ Process and move images after analysis

Run the script with:
```bash
python main.py
```

🚀 Run on Google Colab
If you prefer running the code on Google Colab, use the following notebook:


https://colab.research.google.com/drive/1IvhUnJ5JT0iXzt_eNTR_E6MtkYBLlXON?usp=sharing


📌 Example Usage (from main.py)
```python


from ee_preprocess import load_and_validate_geojson, create_data_cube
from ee_logistic import export_image_to_gcs, move_image_after_analysis

# ✅ Define parameters
bucket_name = "gchm-predictions-test"
geojson_path = "AOI/AoI_Florida.json"
date_range = ("2023-06-01", "2023-06-30")
indices = ["S2", "NDVI", "NDWI"]
input_folder = "rasterdiv_data"
output_folder = "rasterdiv_map"

# ✅ Load AOI from GCS
aoi = load_and_validate_geojson(bucket_name, geojson_path)

# ✅ Create a data cube with Sentinel-2 & vegetation indices
data_cube = create_data_cube(aoi, date_range[0], date_range[1], indices=indices)

# ✅ Export images to GCS
for i in range(data_cube.size().getInfo()):
    image = data_cube.toList(data_cube.size()).get(i)
    export_image_to_gcs(image, f"image_{i}.tif", bucket_name, input_folder, aoi)

print("🎉 Processing Complete!")
```
<img width="552" alt="Capture d’écran 2025-03-19 à 15 30 07" src="https://github.com/user-attachments/assets/68018e5e-49e1-4b97-9469-1ed8f2a39b02" />
Sentinel-2
<img width="556" alt="Capture d’écran 2025-03-19 à 15 29 43" src="https://github.com/user-attachments/assets/d4627d90-cb06-4f6e-a030-cb4161c68df7" />
NDVI
<img width="551" alt="Capture d’écran 2025-03-19 à 15 28 14" src="https://github.com/user-attachments/assets/d3291d1f-4115-4df1-8ad8-a4e55f9ecdce" />
NDWI
