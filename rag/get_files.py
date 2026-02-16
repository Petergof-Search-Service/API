import os
import json
import asyncio
import boto3
from dotenv import load_dotenv


load_dotenv()
ACCESS_KEY=os.getenv("ACCESS_KEY")
SECRET_KEY=os.getenv("SECRET_KEY_OCR")
BUCKET_NAME = "markup-baket"


def get_files():
    metadata_filepath = "data/metadata/metadata.json"

    s3_client = boto3.client(
    "s3",
    endpoint_url="https://storage.yandexcloud.net",
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
    )
    
    response = s3_client.get_object(Bucket=BUCKET_NAME, Key=metadata_filepath)
    metadata = json.load(response['Body'])  # Декодируем содержимое
    print(metadata.keys())
    return sorted(metadata.keys())
    
if __name__ == "__main__":
    get_files()
    