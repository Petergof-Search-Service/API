import base64
import asyncio
import aiohttp
from PyPDF2 import PdfReader, PdfWriter


class YandexOCRAsync:
    def __init__(self, iam_token, folder_id):
        """
        Initialize Yandex OCR client with async support
        """
        self.iam_token = iam_token
        self.folder_id = folder_id
        self.headers = {
            "Authorization": f"Bearer {iam_token}",
            "x-folder-id": folder_id
        }

    def encode_pdf(self, file_path):
        """Encode PDF file to Base64."""
        with open(file_path, 'rb') as file:
            return base64.b64encode(file.read()).decode('utf-8')

    def split_pdf(self, input_path, pages_per_chunk=1):
        """
        Split PDF into smaller chunks.
        """
        chunks = []
        reader = PdfReader(input_path)
        total_pages = len(reader.pages)

        for start_page in range(0, total_pages, pages_per_chunk):
            end_page = min(start_page + pages_per_chunk, total_pages)
            writer = PdfWriter()

            for page_num in range(start_page, end_page):
                writer.add_page(reader.pages[page_num])

            chunk_path = f"./ocr/temp_chunk_{start_page}.pdf"
            with open(chunk_path, 'wb') as output:
                writer.write(output)
            chunks.append((chunk_path, start_page))

        return chunks

    async def recognize_pdf(self, session, file_path):
        """
        Async submit PDF for OCR recognition.
        """
        url = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeTextAsync"

        body = {
            "mimeType": "application/pdf",
            "languageCodes": ["*"],
            "model": "page",
            "content": self.encode_pdf(file_path)
        }

        async with session.post(
                url,
                headers={**self.headers, "Content-Type": "application/json"},
                json=body
        ) as response:
            if response.status == 200:
                data = await response.json()
                operation_id = data.get("id")
                if not operation_id:
                    print(f"Get id failed {file_path}")
                return operation_id
            print(f"Recognition failed: {response.status} - {await response.text()}")

    async def get_operation_result(self, session, operation_id, max_retries=10, delay=10):
        """
        Async get OCR operation result with retries.
        """
        url = f"https://ocr.api.cloud.yandex.net/ocr/v1/getRecognition?operationId={operation_id}"

        for _ in range(max_retries):
            try:
                async with session.get(url, headers=self.headers) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 404:  # Still processing
                        await asyncio.sleep(delay)
                    else:
                        print(f"Failed to get result: {response.status} - {await response.text()}")
            except Exception as e:
                print(e)
        print(f"Operation timed out after {max_retries * delay} seconds")

    def extract_text_from_result(self, ocr_result):
        """
        Extract text blocks with coordinates & bounding box from the OCR result.
        """
        full_text = []

        if not ocr_result or 'result' not in ocr_result:
            return ""

        result = ocr_result['result']
        t_annot = result.get('textAnnotation', {})

        blocks = t_annot.get('blocks', [])
        for block in blocks:
            for line in block.get('lines', []):
                if 'text' not in line:
                    continue
                full_text.append(line['text'])

        return '\n'.join(full_text)

    async def process_chunk(self, session, chunk_path, page_number, semaphore):
        async with semaphore:
            operation_id = await self.recognize_pdf(session, chunk_path)
            if operation_id is None:
                raise Exception("Failed to get operation result")
            ocr_result = await self.get_operation_result(session, operation_id)
            return {
                "page": page_number + 1,
                "text": self.extract_text_from_result(ocr_result)
            }

    async def process_pdf(self, input_path, max_concurrent=10):
        chunks = self.split_pdf(input_path)
        semaphore = asyncio.Semaphore(max_concurrent)

        async with aiohttp.ClientSession() as session:
            tasks = [
                asyncio.create_task(self.process_chunk(session, chunk_path, page_number, semaphore))
                for page_number, (chunk_path, _) in enumerate(chunks)
            ]
            ocr_results = await asyncio.gather(*tasks)

            return sorted(ocr_results, key=lambda x: x["page"])
