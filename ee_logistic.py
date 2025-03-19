from google.cloud import storage
import ee
import json
import os
from datetime import datetime, timedelta
import time
import numpy as np
import requests
from io import BytesIO
import shutil

import google.auth
from google.oauth2 import service_account



def initialize_gee(service_account_key_path, project_id="canopy-height-model-00"):
    """Initialise Google Earth Engine avec un fichier JSON de compte de service et force l'utilisation du projet."""
    try:
        # Définir la variable d'environnement pour le projet
        os.environ['GOOGLE_CLOUD_PROJECT'] = project_id

        credentials = service_account.Credentials.from_service_account_file(
            service_account_key_path,
            scopes=['https://www.googleapis.com/auth/cloud-platform',
                    'https://www.googleapis.com/auth/earthengine']
        )

        # Initialiser GEE avec le projet
        ee.Initialize(credentials, project=project_id)

        print(f"✅ Earth Engine initialized successfully with service account: {credentials.service_account_email}")
        print(f"📢 Projet used for Earth Engine : {project_id}")

    except Exception as e:
        print(f"❌ Erreur d'initialisation Earth Engine : {e}")



def export_image_to_gcs(image,folder, file_name, bucket_name, polygon):
    """ Exporte l'image vers GCS dans le dossier DATASET_GEE_TIF/ et attend la fin du traitement."""
    
    # On stocke les images dans le dossier "rasterdiv/" du bucket
    file_path = f"{folder}/{file_name}"

    task = ee.batch.Export.image.toCloudStorage(
        image=image,
        description=file_name,
        bucket=bucket_name,  # Utilisation du bucket spécifié
        fileNamePrefix=file_path,  # On met le fichier dans "DATASET_GEE_TIF/"
        scale=10,
        region=polygon,
        crs='EPSG:4326',
        fileFormat='GeoTIFF',
        maxPixels=1e9
    )
   

    # Afficher le compte de service utilisé par GEE
    task.start()

    # Attendre la fin de l'exportation
    while task.active():
        print(f"📤 Exporting {file_name} to gs://{bucket_name}/{file_path}...")
        time.sleep(30)  # Pause de 30 secondes avant de revérifier
    
    print(f"✅ Export of {file_name} completed to gs://{bucket_name}/{file_path}.")




def move_image_after_analysis(image_name, input_folder, output_folder, bucket_name):
    """Moves an image from the specified input folder to the output folder in GCS after processing."""

    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    # ✅ Use specified input and output folders
    source_blob_name = f"{input_folder}/{image_name}"  
    destination_blob_name = f"{output_folder}/{image_name}"  

    # ✅ Check if the file exists in GCS before moving
    source_blob = bucket.blob(source_blob_name)
    if not source_blob.exists():
        print(f"❌ Image {source_blob_name} not found in GCS bucket {bucket_name}.")
        return

    # ✅ Copy the image to the new folder
    bucket.copy_blob(source_blob, bucket, new_name=destination_blob_name)

    # ✅ Delete the original file to prevent duplication
    source_blob.delete()

    print(f"✅ Image moved from gs://{bucket_name}/{source_blob_name} to gs://{bucket_name}/{destination_blob_name}")



