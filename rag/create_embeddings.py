import asyncio
import os
import sys
import io
import numpy as np
from langchain.text_splitter import RecursiveCharacterTextSplitter
import torch
from dotenv import load_dotenv
from yandex_cloud_ml_sdk import YCloudML
from tqdm import tqdm
import json
import shutil
from collections import defaultdict
import boto3

load_dotenv()
DATA_DIR = os.getenv("DATA_DIR")
YC_API_KEY = os.getenv("YC_API_KEY")
YC_FOLDER_ID = os.getenv("YC_FOLDER_ID")
ACCESS_KEY=os.getenv("ACCESS_KEY")
SECRET_KEY=os.getenv("SECRET_KEY_OCR")
BUCKET_NAME = "markup-baket"


METADATA_PATH = "data/metadata"
CHUNKS_PATH = "data/chunks"
EMBEDS_PATH = "data/embeddings"
DEST_DIR = "knowledge/data_embedded"


def get_embeddings(file_name_txt):
    
    s3_client = boto3.client(
        "s3",
        endpoint_url="https://storage.yandexcloud.net",
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
    )
    
    file_name_json = os.path.splitext(file_name_txt)[0] + ".json"
    
    folder_path = f"knowledge/{DATA_DIR}"
    metadata_file = os.path.join(METADATA_PATH, "metadata.json")

    sdk = YCloudML(folder_id=YC_FOLDER_ID, auth=YC_API_KEY)
    doc_model = sdk.models.text_embeddings("doc")
    
    response = s3_client.get_object(Bucket=BUCKET_NAME, Key=metadata_file)['Body'].read().decode('utf-8')
    
    if not response:
        metadata = {}
    else:
        metadata = json.loads(response)
    
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    
    file_path = os.path.join(folder_path, file_name_json)
    response = s3_client.get_object(Bucket=BUCKET_NAME, Key=file_path)['Body'].read().decode('utf-8')
    
    if not response:
        file = {}
    else:
        file = json.loads(response)
    
    chunks_file = os.path.join(CHUNKS_PATH, f"{file_name_txt}_chunks.json")
    chunks_data = {'data': []}
    total_chunks = []
    entry_index = 0
    
    for value in file['data']:
        page = value['page']
        text = value['text']
        
        file_chunks = splitter.split_text(text)
        total_chunks += file_chunks
        
        for chunk in file_chunks:
            chunks_data["data"].append({"text": chunk, "page": page})
            entry_index += 1
 
    embeddings = np.array([doc_model.run(chunk) for chunk in  tqdm(total_chunks)], dtype="float32")
    embedding_file = os.path.join(EMBEDS_PATH, f"{file_name_txt}.npy")
    
    buffer = io.BytesIO()
    np.save(buffer, embeddings)
    buffer.seek(0)
    
    s3_client.put_object(
    Bucket=BUCKET_NAME,
    Key=embedding_file,
    Body=buffer.getvalue(),
    ContentType="application/octet-stream"
    )
    
    s3_client.put_object(
    Bucket=BUCKET_NAME,
    Key=chunks_file,
    Body=json.dumps(chunks_data, indent=4),
    ContentType="application/json"
    )
        
    metadata[file_name_txt] = {
        "chunks_file": chunks_file,
        "embedding_file": embedding_file,
        "num_chunks": len(total_chunks)
    }
    s3_client.put_object(
    Bucket=BUCKET_NAME,
    Key=metadata_file,
    Body=json.dumps(metadata, indent=4),
    ContentType="application/json"
    )

    copy_path = os.path.join(DEST_DIR, file_name_json)

    s3_client.copy_object(
    Bucket=BUCKET_NAME,
    CopySource={'Bucket': BUCKET_NAME, 'Key': file_path},
    Key=copy_path
    )

    s3_client.delete_object(Bucket=BUCKET_NAME, Key=file_path)

                
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Недостаточно параметров запуска")
        sys.exit(1)
    
    file_name = sys.argv[1]
    get_embeddings(file_name)
