import os
import re
import pandas as pd
import json
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

# Get current username & Storage Account
username = os.getlogin()
storage_account_name = "yourvalue"

def get_directory_client_for_path(file_system_client, path):
    directory_name = path.rsplit('/', 1)[0]
    return file_system_client.get_directory_client(directory_name)

# Initialise Service Client
default_credential = DefaultAzureCredential()

# Initialise BlobServiceClient
blob_service_client = BlobServiceClient(account_url="https://{}.blob.core.windows.net".format(storage_account_name), credential=default_credential)
print(blob_service_client.url)

# Get the ADLS Container
container_client = blob_service_client.get_container_client("yourvalue")
container_name = "yourvalue"

# Iterate over all files in Container
blobs = container_client.list_blobs()
for blob in blobs:
    # Process only Excel Files
    if not blob.name.endswith('xlsx'):
        continue

    print(f"Processing file: {blob.name}")

    # Download the file
    blob_client = container_client.get_blob_client(blob.name)
    blob_data = blob_client.download_blob().readall()

    # Use BytesIO to convert file
    from io import BytesIO

    # Convert Excel file into dataframes
    xls = pd.ExcelFile(BytesIO(blob_data))
    sheet_to_df_map = {}
    for sheet_name in xls.sheet_names:
        if sheet_name == "Overview":
            continue
        df = xls.parse(sheet_name)
        df['sheetName'] = sheet_name  # Add a new column with the sheet name
        df['ReportName'] = blob.name.split('/')[-1].split('.')[0]
        print(f"Setting ReportName as: {df['ReportName'].iloc[0]} for blob: {blob.name}")
        df.rename(columns=lambda x: re.sub(r'\W+', '', x.replace(' ', '_').replace('%', 'Percent').replace('*', '').replace('1y', 'OneY')), inplace=True)
    
        # Rename Unnamed Columns
        if 'Unnamed_0' in df.columns:
            df.rename(columns={'Unnamed_0' : 'Type'}, inplace=True)

        # Create UniqueId
        df['UniqueId'] = df['ReportName'] + '_' + df['sheetName'] + '_' + df.index.astype(str)
        sheet_to_df_map[sheet_name] = df

    # Convert dataframes into JSON and store back into Azure Data Lake
    for sheet_name, df in sheet_to_df_map.items():
        json_directory = "yourvalue/"
        json_file_name = "yourvalue/" + df['ReportName'].iloc[0] + "_" + sheet_name + ".json"
        print(f"Attempting to save to: {json_file_name}")
        json_str = df.to_json(orient='records')  # Convert dataframe to JSON
        json_blob_client = blob_service_client.get_blob_client(container=container_name, blob=json_file_name)
        json_blob_client.upload_blob(json_str, overwrite=True)
