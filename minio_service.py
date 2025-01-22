from minio import Minio
from minio.error import S3Error
import os
import logging
from io import BytesIO
from datetime import timedelta
import tempfile


logger = logging.getLogger(__name__)

class MinioService:
    def __init__(self):
        self.bucket_name = os.getenv('BUCKET_NAME')
        bucket_host = os.getenv('BUCKET_HOST')
        access_key = os.getenv('BUCKET_ACCESS')
        secret_key = os.getenv('BUCKET_SECRET')

        if not all([self.bucket_name, bucket_host, access_key, secret_key]):
            raise ValueError("Missing one of the required Minio environment variables")

        # Set secure based on RUNNING_LOCALLY environment variable
        is_running_locally = os.getenv('RUNNING_LOCALLY', 'false').lower() == 'true'

        # Initialize the MinIO client using settings from config
        self.client = Minio(
            bucket_host,
            access_key=access_key,
            secret_key=secret_key,
            secure=is_running_locally  
        )

    def ping(self):
        """Simple health check for MinIO connection."""
        try:
            # Just check if we can make a basic API call
            self.client.bucket_exists(self.bucket_name)
            return True
        except Exception as e:
            logger.error(f"MinIO health check failed: {e}")
            return False
        
    def upload_file_from_bytes(self, object_name, file_data, content_type='application/octet-stream'):
        """Uploads a file to the specified bucket from a BytesIO object."""
        try:
            self.client.put_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                data=file_data,
                length=file_data.getbuffer().nbytes,
                content_type=content_type
            )
            logger.debug(f"File '{object_name}' uploaded successfully to bucket '{self.bucket_name}'.")
        except S3Error as e:
            logger.error("Failed to upload file from bytes:", e)


    def download_file_as_bytes(self, object_name):
        """Downloads a file from the specified bucket and returns it as bytes."""
        try:
            response = self.client.get_object(self.bucket_name, object_name)
            data = BytesIO(response.read())
            logger.debug(f"File '{object_name}' downloaded successfully from bucket '{self.bucket_name}'.")
            return data.getvalue()
        except S3Error as e:
            logger.error(f"Failed to download file as bytes: {e}")
            return None
        
        
    def upload_file(self,  object_name, file_path):
        """Uploads a file to a specified bucket."""
        try:
            self.client.fput_object(self.bucket_name, object_name, file_path)
            logger.debug(f"File '{file_path}' uploaded as '{object_name}' to bucket '{self.bucket_name}'.")
        except S3Error as e:
            logger.error("Failed to upload file:", e)

    def download_file(self, object_name, file_path):
        """Downloads a file from a specified bucket."""
        try:
            self.client.fget_object(self.bucket_name, object_name, file_path)
            logger.debug(f"File '{object_name}' from bucket '{self.bucket_name}' downloaded to '{file_path}'.")
        except S3Error as e:
            logger.error("Failed to download file:", e)


    def generate_presigned_url(self, object_name, expiration=timedelta(days=7)):
        """
        Generates a pre-signed URL for downloading an object, valid for a specified expiration time.
        
        :param object_name: The name of the object in the bucket for which to generate the URL.
        :param expiration: A datetime.timedelta object representing how long the URL should be valid. 
                           Default is 3600 seconds (1 hour).
        """
        try:
            # Note: the `expires` parameter now directly uses the timedelta object
            url = self.client.presigned_get_object(self.bucket_name, object_name, expires=expiration)
            logger.debug(f"Pre-signed URL generated for '{object_name}' in bucket '{self.bucket_name}'.")
            return url
        except S3Error as e:
            logger.error(f"Failed to generate pre-signed URL: {e}")
            return None
        
    def stream_object(self, object_name):
        """
        Retrieves an object from the bucket as a stream.
        :param object_name: The name of the object in the bucket.
        :return: The object data as a BytesIO stream.
        """
        try:
            response = self.client.get_object(self.bucket_name, object_name)
            logger.debug(f"Object '{object_name}' retrieved successfully from bucket '{self.bucket_name}'.")
            return response
        except S3Error as e:
            logger.error(f"Failed to retrieve object '{object_name}': {e}")
            return None


    def get_object(self, object_name):
        """
        Retrieves an object from the bucket as a stream.
        :param object_name: The name of the object in the bucket.
        :return: The path of the temporary file containing the object data.
        """
        try:
            response = self.client.get_object(self.bucket_name, object_name)
            with tempfile.NamedTemporaryFile(delete=False) as temp:
                for data in response.stream(32*1024):
                    temp.write(data)
                temp_filepath = temp.name
            logger.debug(f"Object '{object_name}' retrieved successfully from bucket '{self.bucket_name}'.")
            return temp_filepath
        except S3Error as e:
            logger.error(f"Failed to retrieve object '{object_name}': {e}")
            return None

    
    def delete_file(self, object_name):
        """Deletes a file from the specified bucket."""
        try:
            self.client.remove_object(self.bucket_name, object_name)
            logger.debug(f"File '{object_name}' deleted successfully from bucket '{self.bucket_name}'.")
        except S3Error as e:
            logger.error(f"Failed to delete file '{object_name}': {e}")


    def list_files_in_folder(self, folder_name):
        """Lists all files in a specified folder within the bucket."""
        try:
            objects = self.client.list_objects(self.bucket_name, prefix=folder_name, recursive=True)
            file_list = [os.path.basename(obj.object_name) for obj in objects]
            logger.info(f"Files in folder '{folder_name}' listed successfully.")
            return file_list
        except S3Error as e:
            logger.error(f"Failed to list files in folder '{folder_name}': {e}")
            return []
        

    def copy_object(self, source_object_name, target_object_name):
        """Copies an object from one location to another within the same bucket."""
        try:
            self.client.copy_object(
                self.bucket_name,
                target_object_name,
                f"/{self.bucket_name}/{source_object_name}"
            )
            logger.debug(f"Object '{source_object_name}' copied to '{target_object_name}' in bucket '{self.bucket_name}'.")
        except S3Error as e:
            logger.error(f"Failed to copy object '{source_object_name}': {e}")

    def move_object(self, source_object_name, target_object_name):
        """Moves an object from one location to another within the same bucket."""
        try:
            self.copy_object(source_object_name, target_object_name)
            self.delete_file(source_object_name)
            logger.debug(f"Object '{source_object_name}' moved to '{target_object_name}' in bucket '{self.bucket_name}'.")
        except S3Error as e:
            logger.error(f"Failed to move object '{source_object_name}': {e}")


    def object_exists(self, object_name, max_retries=3, backoff_factor=0.5):
        """Check if an object exists in Minio with retry logic"""
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=[500, 502, 503, 504]
        )
        
        self.client._http.set_retry_policy(retry_strategy)
        
        try:
            objects = self.client.list_objects(self.bucket_name, prefix=object_name)
            exists = any(obj.object_name == object_name for obj in objects)
            return exists
        except Exception as e:
            logger.warning(f"Failed to check if object {object_name} exists: {str(e)}")
            # If we can't check if the object exists, assume it doesn't
            # This is safer than failing the whole operation
            return False
