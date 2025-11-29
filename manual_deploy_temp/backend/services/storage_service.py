import boto3
import os
import logging
from botocore.exceptions import ClientError
from backend.core.config import settings
from pathlib import Path

logger = logging.getLogger(__name__)

class StorageService:
    def __init__(self):
        self.bucket_name = settings.R2_BUCKET_NAME
        self.endpoint_url = settings.R2_ENDPOINT_URL
        self.s3_client = None
        
        if settings.R2_ACCESS_KEY_ID and settings.R2_SECRET_ACCESS_KEY:
            try:
                self.s3_client = boto3.client(
                    's3',
                    endpoint_url=self.endpoint_url,
                    aws_access_key_id=settings.R2_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
                    region_name='auto' # R2 uses 'auto'
                )
            except Exception as e:
                logger.error(f"Failed to initialize R2 client: {e}")

    def generate_presigned_url(self, object_name: str, expiration=3600) -> str:
        """Generate a presigned URL to share an S3 object"""
        if not self.s3_client:
            return ""
        try:
            response = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': object_name},
                ExpiresIn=expiration
            )
            return response
        except ClientError as e:
            logger.error(f"Error generating presigned URL: {e}")
            return ""

    def list_files(self, prefix: str = "") -> list:
        """List files in the bucket with a prefix"""
        if not self.s3_client:
            return []
        try:
            response = self.s3_client.list_objects_v2(Bucket=self.bucket_name, Prefix=prefix)
            return [obj['Key'] for obj in response.get('Contents', [])]
        except ClientError as e:
            logger.error(f"Error listing files: {e}")
            return []

    def download_file(self, object_name: str, dest_path: Path) -> bool:
        """Download a file from the bucket"""
        if not self.s3_client:
            return False
        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            self.s3_client.download_file(self.bucket_name, object_name, str(dest_path))
            return True
        except ClientError as e:
            logger.error(f"Error downloading file {object_name}: {e}")
            return False

    def upload_file(self, file_path: Path, object_name: str = None) -> bool:
        """Upload a file to the bucket"""
        if not self.s3_client:
            return False
        if object_name is None:
            object_name = file_path.name
        try:
            self.s3_client.upload_file(str(file_path), self.bucket_name, object_name)
            return True
        except ClientError as e:
            logger.error(f"Error uploading file {file_path}: {e}")
            return False

storage_service = StorageService()
