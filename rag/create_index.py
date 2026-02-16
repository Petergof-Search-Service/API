import os
import io
import sys
import faiss
import numpy as np
import pickle
from langchain.text_splitter import RecursiveCharacterTextSplitter
from transformers import AutoModel, AutoTokenizer
import torch
from dotenv import load_dotenv
from yandex_cloud_ml_sdk import YCloudML
from tqdm import tqdm
import json
from .get_indexes import get_indexes
from rank_bm25 import BM25Okapi
import re
import boto3

load_dotenv()
DATA_DIR = os.getenv("DATA_DIR")
YC_API_KEY = os.getenv("YC_API_KEY")
YC_FOLDER_ID = os.getenv("YC_FOLDER_ID")
ACCESS_KEY=os.getenv("ACCESS_KEY")
SECRET_KEY=os.getenv("SECRET_KEY_OCR")
BUCKET_NAME = "markup-baket"

RAG_PATH = "data/rag"
METADATA_PATH = "data/metadata"
CHUNKS_PATH = "data/chunks"
EMBEDS_PATH = "data/embeddings"
USING_FILES_PATH = "data/using_files/files.txt"


def preprocess_text(text):
    text = re.sub(r"[^\w\s]", "", text).lower()
    return text.split()

def create_index(name, selected_files):
    if name in get_indexes():
        print("Индекс с таким именем уже существует")
        return
    
    s3_client = boto3.client(
        "s3",
        endpoint_url="https://storage.yandexcloud.net",
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
    )
    
    meta_path = os.path.join(METADATA_PATH, "metadata.json")

    # with open(meta_path, "r", encoding="utf-8") as meta_file:
    #     metadata = json.load(meta_file)
    
    response = s3_client.get_object(Bucket=BUCKET_NAME, Key=meta_path)['Body'].read().decode('utf-8')
    
    if not response:
        metadata = {}
    else:
        metadata = json.loads(response)

    if not selected_files:
        print("Нет выбранных файлов для загрузки в индекс.")
        return

    all_embeddings = []
    all_chunks = []
    all_metadata = []

    for filename in selected_files:
        if filename not in metadata:
            continue
            
        file_info = metadata[filename]
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=file_info["embedding_file"])
        buffer = io.BytesIO(response['Body'].read())
        
        embeddings = np.load(buffer)
        
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=file_info["chunks_file"])['Body'].read().decode('utf-8')
        if not response:
            chunks = {}
        else:
            chunks = json.loads(response)
        
        all_embeddings.append(embeddings)
        all_chunks.extend([elem["text"] for elem in chunks['data']])
        all_metadata.extend([(filename, elem["page"]) for elem in chunks['data']])

    if not all_embeddings:
        print("Нет эмбеддингов для добавления в индекс.")
        return

    all_embeddings = np.vstack(all_embeddings)
    
    dimension = 256
    M = 256
    efConstruction = 400
    index = faiss.IndexHNSWFlat(dimension, M)
    index.hnsw.efConstruction = efConstruction
    index.hnsw.efSearch = 256
    print(len(selected_files))
    
    tokenized_chunks = [preprocess_text(chunk) for chunk in all_chunks]
    bm25 = BM25Okapi(tokenized_chunks)
    
    index.add(all_embeddings)
    
    buffer_path = os.path.join(RAG_PATH, f"index_{name}.faiss")
    LOCAL_FILE = f"rag/tmp/index_{name}.faiss"

    faiss.write_index(index, LOCAL_FILE)
    s3_client.upload_file(LOCAL_FILE, BUCKET_NAME, buffer_path)
    os.remove(LOCAL_FILE)

    #     with open(os.path.join(RAG_PATH, f"metadata_{name}.pkl"), "wb") as f:
    #         pickle.dump(all_metadata, f)
                               
    pickle_buffer = io.BytesIO()
    pickle.dump(all_metadata, pickle_buffer)
    pickle_buffer.seek(0)

    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=os.path.join(RAG_PATH, f"metadata_{name}.pkl"),
        Body=pickle_buffer.getvalue(),
        ContentType="application/octet-stream"
    )

    # with open(os.path.join(RAG_PATH, f"chunks_{name}.pkl"), "wb") as f:
    #     pickle.dump(all_chunks, f)
    
    pickle_buffer = io.BytesIO()
    pickle.dump(all_chunks, pickle_buffer)
    pickle_buffer.seek(0)

    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=os.path.join(RAG_PATH, f"chunks_{name}.pkl"),
        Body=pickle_buffer.getvalue(),
        ContentType="application/octet-stream"
    )
       
    # with open(os.path.join(RAG_PATH, f"bm25_{name}.pkl"), 'wb') as f:
    #     pickle.dump(bm25, f)
    
    pickle_buffer = io.BytesIO()
    pickle.dump(bm25, pickle_buffer)
    pickle_buffer.seek(0)

    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=os.path.join(RAG_PATH, f"bm25_{name}.pkl"),
        Body=pickle_buffer.getvalue(),
        ContentType="application/octet-stream"
    )
    
    list_indexes_path = os.path.join(METADATA_PATH, "list_indexes.json")
                               
    response = s3_client.get_object(Bucket=BUCKET_NAME, Key=list_indexes_path)['Body'].read().decode('utf-8')
    
    if not response:
        list_indexes = {}
    else:
        list_indexes = json.loads(response)
            
    list_indexes[name] = {"files": selected_files}
                               
    # with open(os.path.join(list_indexes_path), "w", encoding="utf-8") as f:
    #     json.dump(list_indexes, f, ensure_ascii=False, indent=4)
    
    s3_client.put_object(
    Bucket=BUCKET_NAME,
    Key=os.path.join(list_indexes_path),
    Body=json.dumps(list_indexes, indent=4),
    ContentType="application/json"
    )
    
    print(f"Индекс сохранён. Записей: {index.ntotal}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Недостаточно параметров запуска")
        sys.exit(1)
    
    example = ['ab83a5d6362983ec339ce0a1ce2b732a.txt', 
           'Майкова_Военные_журналы_юрналы_Петра_1.txt', 
           ]

    create_index(sys.argv[1], example)
