# storage_utils.py
import boto3
from botocore.client import Config
import streamlit as st
import base64

def create_s3_client():
    supabase_url = st.secrets["supabase"]["url"]
    aws_access_key_id = st.secrets["s3"]["aws_access_key_id"]
    aws_secret_access_key = st.secrets["s3"]["aws_secret_access_key"]
    
    # Create an S3 client using Supabase's S3-compatible endpoint.
    # The Supabase storage endpoint usually follows this pattern:
    endpoint_url = f"{supabase_url}/storage/v1"
    
    s3 = boto3.client(
        's3',
        endpoint_url=endpoint_url,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        config=Config(signature_version='s3v4')
    )
    return s3


def fetch_image(selected_fach, image_filename):
    """
    Fetch an image from Supabase storage using the S3 protocol.
    
    Parameters:
      - selected_fach: The folder/name (e.g., "EAM") where images are stored.
      - image_filename: The filename of the image (e.g., "Praktikumsvertrag (Deutsch)_page_2.png").
    
    Returns:
      - The image bytes or raises an Exception if the image could not be fetched.
    """
    bucket_name = st.secrets["supabase"]["bucket"]
    object_key = f"{selected_fach}/images/{image_filename}"
    s3 = create_s3_client()
    
    try:
        response = s3.get_object(Bucket=bucket_name, Key=object_key)
        image_bytes = response['Body'].read()
        return image_bytes
    except Exception as e:
        raise Exception(f"Error fetching image from S3: {e}")

def get_image_as_data_url(selected_fach, image_filename):
    """
    Convenience function that returns the image as a data URL for display.
    """
    image_bytes = fetch_image(selected_fach, image_filename)
    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    # Adjust image/png if you expect another image type.
    data_url = f"data:image/png;base64,{base64_image}"
    return data_url
