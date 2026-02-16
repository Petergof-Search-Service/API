import json
import os

import boto3
from dotenv import load_dotenv

load_dotenv()
ACCESS_KEY=os.getenv("ACCESS_KEY")
SECRET_KEY=os.getenv("SECRET_KEY_OCR")
BUCKET_NAME = "markup-baket"

def get_indexes():
    list_indexes_filepath = "data/metadata/list_indexes.json"
    s3_client = boto3.client(
        "s3",
        endpoint_url="https://storage.yandexcloud.net",
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
    )
    
    response = s3_client.get_object(Bucket=BUCKET_NAME, Key=list_indexes_filepath)
    list_indexes = json.load(response['Body'])
    
    return list(list_indexes.keys())
    

def get_files_by_index_name(name):
    list_indexes_filepath = "data/metadata/list_indexes.json"
    s3_client = boto3.client(
        "s3",
        endpoint_url="https://storage.yandexcloud.net",
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
    )
    
    response = s3_client.get_object(Bucket=BUCKET_NAME, Key=list_indexes_filepath)
    list_indexes = json.load(response['Body'])
            
    if name in list_indexes.keys():
        return sorted(list_indexes[name]['files'])
    
    print('Несуществующий индекс')
    return None
    
    
if __name__ == "__main__":
    get_indexes()
    get_files_by_index_name("new")
    