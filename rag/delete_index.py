import os
import json
import boto3
from dotenv import load_dotenv
import sys
import io

load_dotenv()
ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY_OCR")
BUCKET_NAME = "markup-baket"

def delete_ind(index_name):
    list_indexes_filepath = "data/metadata/list_indexes.json"
    rag_base_path = "data/rag/"
    s3_client = boto3.client(
        "s3",
        endpoint_url="https://storage.yandexcloud.net",
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
    )

    response = s3_client.get_object(Bucket=BUCKET_NAME, Key=list_indexes_filepath)
    list_indexes = json.load(response["Body"])

    if index_name not in list_indexes:
        print(f"Индекс '{index_name}' не найден.")
        return False

    response = s3_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=rag_base_path)
    if "Contents" in response:
        for obj in response["Contents"]:
            key = obj["Key"]
            filename = os.path.basename(key)
            if filename.endswith(f"_{index_name}.pkl") or \
                    filename.endswith(f"_{index_name}.faiss"):
                s3_client.delete_object(Bucket=BUCKET_NAME, Key=key)

    del list_indexes[index_name]

    json_buffer = io.BytesIO()
    json_str = json.dumps(list_indexes, indent=2)
    json_buffer.write(json_str.encode('utf-8'))
    json_buffer.seek(0)

    s3_client.upload_fileobj(json_buffer, BUCKET_NAME, list_indexes_filepath)
    print(f"Индекс {index_name} удален")
    return True
