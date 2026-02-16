import faiss
import numpy as np
import pickle
import re
from dotenv import load_dotenv
import os
from yandex_cloud_ml_sdk import YCloudML
from rank_bm25 import BM25Okapi
import aiobotocore.session
import asyncio
import uuid

load_dotenv()

YC_API_KEY = os.getenv("YC_API_KEY")
YC_FOLDER_ID = os.getenv("YC_FOLDER_ID")
ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY_OCR")
BUCKET_NAME = "markup-baket"
RAG_PATH = "data/rag"


def preprocess_text(text):
    text = re.sub(r"[^\w\s]", "", text).lower()
    return text.split()


async def download_s3_bytes(s3_client, key):
    response = await s3_client.get_object(Bucket=BUCKET_NAME, Key=key)
    async with response["Body"] as stream:
        return await stream.read()


async def get_lists(index_name, question, faiss_search, bm_search):
    session = aiobotocore.session.get_session()
    async with session.create_client(
            "s3",
            region_name="ru-central1",
            endpoint_url="https://storage.yandexcloud.net",
            aws_access_key_id=ACCESS_KEY,
            aws_secret_access_key=SECRET_KEY,
    ) as s3_client:

        index_bytes, bm25_bytes = await asyncio.gather(
            download_s3_bytes(s3_client, f"{RAG_PATH}/index_{index_name}.faiss"),
            download_s3_bytes(s3_client, f"{RAG_PATH}/bm25_{index_name}.pkl"),
        )

    unique_filename = f"/tmp/temp_index_{uuid.uuid4().hex}.faiss"
    with open(unique_filename, "wb") as f:
        f.write(index_bytes)
    index = faiss.read_index(unique_filename)
    os.remove(unique_filename)

    bm25 = pickle.loads(bm25_bytes)

    sdk = YCloudML(folder_id=YC_FOLDER_ID, auth=YC_API_KEY)
    query_model = sdk.models.text_embeddings("query")
    query_embedding = np.array([query_model.run(question)], dtype=np.float32)

    distances, indices = index.search(query_embedding, faiss_search)

    bm25_scores = bm25.get_scores(preprocess_text(question))
    top_bm25_indices = np.argsort(bm25_scores)[-bm_search:][::-1]

    return indices[0], top_bm25_indices
