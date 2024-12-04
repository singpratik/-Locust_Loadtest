import os
from locust import HttpUser, task, between
import json
import logging
import time
import random
import csv

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Get user credentials from CSV file
def load_user_credentials(file_path):
    credentials = []
    try:
        with open(file_path, mode='r') as csvfile:
            # Use csv.reader to handle the specific format of your file
            reader = csv.reader(csvfile)
            next(reader)  # Skip header row if it exists
            for row in reader:
                # Ensure the row has at least 2 elements (email and password)
                if len(row) >= 2:
                    email = row[0].strip()
                    password = row[1].strip()
                    if email and password:
                        credentials.append({"email": email, "password": password})
                    else:
                        logger.warning(f"Skipping invalid row: {row}")
                else:
                    logger.warning(f"Skipping invalid row: {row}")
    except FileNotFoundError:
        logger.error(f"CSV file not found: {file_path}")
    except Exception as e:
        logger.error(f"Error reading CSV file: {str(e)}")
    
    # Log the number of credentials loaded
    logger.info(f"Loaded {len(credentials)} user credentials")
    
    # Ensure we have credentials
    if not credentials:
        logger.critical("No user credentials loaded. The test cannot proceed.")
    
    return credentials

# Specify the path to your CSV file
CSV_FILE_PATH = '/Users/pratiksingh/Desktop/No-code-automation-demo-main/TopcoderAutomationDemo/LoadTest/user_cred.csv'

# Load user credentials
USER_CREDENTIALS = load_user_credentials(CSV_FILE_PATH)

class InterviewUser(HttpUser):
    wait_time = between(30, 60)
    host = "https://api-uat-us-candidate.vmock.dev"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.access_token = None
        self.user_id = None
        self.upload_limit = 0
        self.failed_uploads = set()
        self.uploaded_resumes = {}
        self.upload_status = []
        self.max_retries = 3
        self.retry_delay = 2

    def on_start(self):
        """Initialize the user session"""
        # Ensure we have credentials before trying to log in
        if not USER_CREDENTIALS:
            logger.critical("No user credentials available. Cannot start user session.")
            return

        # Attempt to log in with multiple retries
        for _ in range(100):
            # Safely choose a random credential
            try:
                self.user_credentials = random.choice(USER_CREDENTIALS)
            except IndexError:
                logger.critical("Failed to choose user credentials. Credentials list is empty.")
                return

            if self.login():
                if self.get_user_id():
                    logger.info(f"User logged in successfully with ID: {self.user_id}")
                    break
                else:
                    logger.error("Failed to fetch user ID.")
                    break
            else:
                logger.warning("Login failed. Retrying with another user.")
                time.sleep(2)
        else:
            logger.error("Failed to login after multiple attempts.") 

    def log_response_data(self, request_name, response_data):
        """
        Log response data for monitoring and debugging purposes
        
        Args:
            request_name (str): Name/identifier for the request
            response_data (dict): Response data to log
        """
        self.environment.events.request.fire(
            request_type="GET",
            name=request_name,
            response_time=int(time.time() * 1000),
            response_length=len(json.dumps(response_data)),
            response=response_data,
            context={},
            exception=None,
        )              

    @task(1)
    def execute_interview_flow(self):
        """Execute the complete interview flow"""
        if not self.access_token or not self.user_id:
            logger.error("No access_token or user_id available to fetch resume data.")
            return
        
        # Get the upload limit
        self.upload_limit = self.get_upload_limit()
        if self.upload_limit is None or self.upload_limit == 0:
            logger.error("Upload limit is already reached.")
            return  # No further uploads allowed

        # Upload PDF files
        self.upload_pdf_files()

        # Process each resume individually with proper delays between each
        for filename, resume_id in self.uploaded_resumes.items():
            logger.info(f"Processing resume {filename} with ID {resume_id}")
            if self.call_upload_resume_builder_api(resume_id):
                logger.info(f"Successfully processed resume {filename}")
                time.sleep(5)  # Add delay between processing different resumes
            else:
                logger.error(f"Failed to process resume {filename}")

        # Call customer feedback status API after processing resumes
        self.call_customer_feedback_status_api()

    def login(self):
        """Perform login and return True if successful"""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "LocustTest/1.0"  # Custom User-Agent (change as needed)
        }
        payload = {
            "email": self.user_credentials["email"],
            "password": self.user_credentials["password"],
            "provider": "email"
        }
        logger.info(f"Attempting to login with email: {self.user_credentials['email']}")

        with self.client.post(
            "/dashboard-api-accounts/api/v1/login/common",
            json=payload,
            headers=headers,
            catch_response=True,
            name="/login"
        ) as response:
            # Check if the response is a valid JSON and if status code is 200
            if response.status_code == 200:
                try:
                    response_data = response.json()
                    logger.info(f"Login response: {response_data}")  # Log the entire response data for debugging

                    self.access_token = response_data.get('access_token')
                    if self.access_token:
                        logger.info(f"Access token successfully retrieved for user: {self.user_credentials['email']}")
                        logger.debug(f"Access Token: {self.access_token}")  # Log the access token for verification
                        logger.info(f"Login successful for user: {self.user_credentials['email']}")
                        return True
                    else:
                        logger.error("Access token not found in the response")
                except ValueError:
                    logger.error(f"Response is not valid JSON: {response.text}")
            else:
                logger.error(f"Login failed for user: {self.user_credentials['email']} with status {response.status_code}")
                logger.error(f"Response content: {response.text}")

        return False
    

    def get_user_id(self):
        """Fetch user_id from the /user/info API"""
        if not self.access_token:
            logger.error("No access_token available to fetch user_id.")
            return False

        api_url = "/dashboard-api-accounts/api/v1/user/info"
        logger.info(f"Fetching user_id from {api_url}...")

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",  # Ensure proper content type for POST requests
        }

        with self.client.post(api_url, headers=headers, catch_response=True, name="/user/info") as response:
            if response.status_code == 200:
                response_data = response.json()
                logger.info(f"User info response: {response_data}")
                self.user_id = response_data.get('id')  # Extract the user_id from the response
                if self.user_id:
                    logger.info(f"Successfully fetched id: {self.user_id}")
                    return True
                else:
                    logger.error("id not found in the response.")
            else:
                logger.error(f"Failed to fetch user info. Status: {response.status_code}, Response: {response.content}")
        
        return False    

    def get_upload_limit(self):
        """Get the upload limit"""
        timestamp = str(int(time.time() * 1000))  # Current timestamp in milliseconds
        api_url = f"/dashboard-api-resume-parser/v1/resume/upload-count?_={timestamp}"

        logger.info("Fetching upload limit...")
        response = self.client.get(api_url)

        if response.status_code == 200:
            response_data = response.json()
            logger.info(f"Upload limit response: {response_data}")
            return response_data.get('remaining', 0)  # Use 'remaining' as the upload limit, default to 0 if not found
        else:
            logger.error(f"Failed to get upload limit. Status: {response.status_code}, Response: {response.content.decode('utf-8')}")
            return 0


    def upload_pdf_files(self):
        """Upload PDF files from a local directory according to the upload limit"""
        pdf_directory = "/Users/pratiksingh/Desktop/No-code-automation-demo-main/TopcoderAutomationDemo/LoadTest/pdf"
        pdf_files = [f for f in os.listdir(pdf_directory) if f.endswith('.pdf')]
        logger.info(f"Found {len(pdf_files)} PDF files to upload.")

        uploaded_count = 0

        # Ensure we get the current upload limit at the start of the process
        if self.upload_limit <= 0:
            logger.info("Upload limit is already 0. Stopping uploads.")
            return

        # Loop through the PDF files and upload them until the limit is reached
        for pdf_file in pdf_files:
            # Before each upload, check if we still have remaining upload slots
            if self.upload_limit <= 0:
                logger.info("Upload limit reached (remaining = 0). Stopping further uploads.")
                break

            # Skip failed uploads
            if pdf_file in self.failed_uploads:
                logger.info(f"Skipping upload for failed resume: {pdf_file}")
                continue

            # Upload the PDF file
            pdf_file_path = os.path.join(pdf_directory, pdf_file)
            logger.info(f"User {self.user_credentials['email']} is uploading: {pdf_file}")

            # Upload the PDF and get resume ID
            resume_id = self.upload_pdf(pdf_file_path)
            if resume_id:
                uploaded_count += 1
                self.uploaded_resumes[pdf_file] = resume_id  # Store resume_id for tracking
                logger.info(f"Uploaded {pdf_file} with resume ID: {resume_id}. Total uploaded: {uploaded_count}")

                # After upload, get the updated upload limit from the server
                self.upload_limit = self.get_upload_limit()  # Re-fetch the upload limit
                logger.info(f"Updated upload limit: {self.upload_limit} remaining, {uploaded_count} uploaded.")

                # Track the status of the uploaded file
                logger.info(f"Tracking status for resume ID {resume_id}...")
                if self.track_file_status(resume_id):
                    logger.info(f"Resume {resume_id} processed successfully.")

                    # After processing is successful, call the /upload-resume API
                    if self.call_upload_resume_builder_api(resume_id):
                        logger.info(f"Successfully called /upload-resume API for resume ID {resume_id}")
                    else:
                        logger.error(f"Failed to call /upload-resume API for resume ID {resume_id}")
                else:
                    logger.error(f"Failed to process resume {resume_id}")

            else:
                logger.error(f"Failed to upload {pdf_file}")
                self.failed_uploads.add(pdf_file)  # Track failed uploads

            # If the upload limit is now 0, stop attempting further uploads
            if self.upload_limit == 0:
                logger.info("Upload limit is now 0. No further uploads allowed.")
                break



        
    def upload_pdf(self, pdf_file_path):
        """Upload a single PDF file and store response data for later use"""
        if not os.path.exists(pdf_file_path):
            logger.error(f"PDF file does not exist: {pdf_file_path}")
            return False

        api_url = f"{self.host}/dashboard-api-resume-parser/v1/resume/upload"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
        }

        data = {
            "product_name": "resume"  # Required product name
        }

        with open(pdf_file_path, 'rb') as pdf_file:
            files = {'resume': pdf_file}
            logger.info(f"Sending request to {api_url} with headers: {headers} and data: {data}")
            response = self.client.post(api_url, files=files, headers=headers, data=data)

            if response.status_code in [200, 201]:
                try:
                    response_data = response.json()
                    resume_id = response_data.get('id')
                      # Get the resume ID from response
                    if resume_id:
                        logger.info(f"Successfully uploaded PDF with resume ID: {resume_id}")

                        # Store the response data in the instance variable
                        self.uploaded_resumes[resume_id] = response_data

                        return resume_id
                    else:
                        logger.error("Resume ID not found in response")
                        return None
                except Exception as e:
                    logger.error(f"Failed to parse response: {str(e)}")
                    return None

            logger.error(f"Failed to upload PDF. Status: {response.status_code}, Response: {response.content}")
            return None

        
    def track_file_status(self, resume_id):
        """Track the status of a specific resume and wait for it to be processed."""
        if not self.access_token:
            logger.error("No access token available to track resume status.")
            return False

        max_retries = 60  # Number of attempts (2 minutes total with 2-second delay)
        processing_timeout = 300  # 5 minutes total maximum wait time

        start_time = time.time()
        attempt = 0

        while time.time() - start_time < processing_timeout and attempt < max_retries:
            attempt += 1
            dynamic_value = str(int(time.time() * 1000))
            api_url = f"/dashboard-api-resume-parser/v1/resume/{resume_id}/status?_={dynamic_value}"

            logger.info(f"Checking status for resume ID {resume_id}, attempt {attempt}/{max_retries}")

            try:
                response = self.client.get(
                    api_url,
                    headers={"Authorization": f"Bearer {self.access_token}"},
                    name="/resume/status"
                )

                if response.status_code == 200:
                    status_data = response.json()  # Store the full response data
                    status = status_data.get('status')
                    logger.info(f"Raw API Response: {status_data}")  # Log the complete API response

                    # Store the entire response data for later use
                    resume_data = {
                        "id": resume_id,
                        "status_data": status_data  # Store the entire response data here
                    }

                    logger.info(f"Resume {resume_id} status: {status_data}")

                    # If the resume is processed and status is 'done'
                    if status == "done":
                        logger.info(f"Resume {resume_id} processing completed successfully.")

                        # You can extract more fields or perform further actions here if needed

                        # Store the processed resume data (with full response)
                        self.uploaded_resumes[resume_id] = resume_data
                        return True  # Successfully processed

                    elif status in ["failed", "error"]:
                        logger.error(f"Resume {resume_id} processing failed with status: {status}")
                        return False
                    elif status == "processing":
                        logger.info(f"Resume {resume_id} is still processing. Waiting...")
                        time.sleep(self.retry_delay)
                    else:
                        logger.warning(f"Resume {resume_id} returned unknown status: {status}")
                        time.sleep(self.retry_delay)

                elif response.status_code == 404:
                    logger.warning(f"Resume {resume_id} not found. May still be initializing...")
                    time.sleep(self.retry_delay)
                else:
                    logger.error(f"Failed to get status for resume {resume_id}. Status code: {response.status_code}")
                    time.sleep(self.retry_delay)

            except Exception as e:
                logger.error(f"Error checking status for resume {resume_id}: {str(e)}")
                time.sleep(self.retry_delay)

        logger.error(f"Resume {resume_id} processing timed out after {int(time.time() - start_time)} seconds.")
        return False
    

    def verify_resume_output(self, resume_id):
        """Retrieve and store resume data after processing is complete."""
        if not self.access_token:
            logger.error("No access token available to retrieve resume data.")
            return None

        api_url = f"{self.host}/dashboard-api-resume-parser/v1/resume/{resume_id}/status"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        for attempt in range(self.max_retries):
            timestamp = int(time.time() * 1000)
            try:
                response = self.client.get(
                    f"{api_url}?_={timestamp}",
                    headers=headers,
                    name="/resume/details",
                    timeout=10
                )

                if response.status_code == 200:
                    resume_data = response.json()

                    if resume_data and isinstance(resume_data, dict):
                        logger.info(f"Resume {resume_id} data retrieved successfully.")
                        
                        # No word count logic, just store the resume data
                        self.uploaded_resumes[resume_id] = resume_data
                        return resume_data
                    else:
                        logger.error(f"Invalid data format received for resume {resume_id}")
                elif response.status_code == 404:
                    logger.error(f"Resume {resume_id} not found.")
                else:
                    logger.error(f"Failed to retrieve resume data. Status code: {response.status_code}")

                if attempt < self.max_retries - 1:
                    logger.info(f"Retrying to retrieve resume data. Attempt {attempt + 1}/{self.max_retries}")
                    time.sleep(self.retry_delay)

            except Exception as e:
                logger.error(f"Error retrieving resume data: {str(e)}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)

        return None

                          

                               

    
    
    def submit_customer_feedback(self, resume_id, status):
        """Submit feedback after processing is complete."""
        api_url = "/dashboard-api-resume-parser/v1/resume/customer-feedback/status"
        feedback_data = {
            "resume_id": resume_id,
            "status": status,
            "message": "Resume processing completed successfully" if status == "done" else "Resume still processing"
        }

        try:
            # Send feedback to the API
            response = self.client.post(
                api_url,
                json=feedback_data,
                headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"},
                catch_response=True
            )

            if response.status_code == 200:
                # Store the entire response data
                response_data = response.json()  # Assuming the response is a JSON object

                # Log the successful feedback submission
                logger.info(f"Feedback for resume {resume_id} submitted successfully. Response data: {response_data}")

                # You can store the response data in a dictionary or database as needed
                self.uploaded_resumes[resume_id] = {
                    "feedback_status": status,
                    "message": feedback_data["message"],
                    "response_data": response_data  # Storing the full response
                }

                return True
            else:
                logger.error(f"Failed to submit feedback for resume {resume_id}. Status: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Error submitting feedback for resume {resume_id}: {str(e)}")
            return False




    def call_upload_resume_builder_api(self, resume_id):
            """Call the /upload-resume API with proper checks and retries"""
            logger.info(f"Starting upload process for resume ID: {resume_id}")
            
            # First wait for resume processing to complete
            if not self.track_file_status(resume_id):
                logger.error(f"Resume {resume_id} processing did not complete successfully")
                return

            # Add a small delay after status check
            time.sleep(2)

            # Verify resume data is available
            if not self.verify_resume_output(resume_id):
                logger.error(f"Resume data not available for ID {resume_id}")
                return

            # Add a small delay after verification
            time.sleep(2)

            api_url = "/dashboard-api-resume-builder/v1/builder/upload-resume"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            logger.info(f"Calling /upload-resume API with resume_id: {resume_id}")

            payload = {
                "dashboard_resume_id": resume_id,
                "csrf_token": self.access_token,
            }

            max_retries = 3
            retry_delay = 2

            for retry_count in range(max_retries):
                try:
                    with self.client.post(api_url, json=payload, headers=headers, catch_response=True) as response:
                        if response.status_code == 200:
                            response_data = response.json()
                            logger.info(f"Successfully uploaded resume {resume_id}. Response: {response_data}")
                            return True
                        else:
                            logger.error(f"Failed to upload resume {resume_id}. Status: {response.status_code}, Response: {response.content}")
                            if retry_count < max_retries - 1:
                                logger.info(f"Retrying upload for resume {resume_id} in {retry_delay} seconds...")
                                time.sleep(retry_delay)
                except Exception as e:
                    logger.error(f"Error during upload for resume {resume_id}: {str(e)}")
                    if retry_count < max_retries - 1:
                        time.sleep(retry_delay)

            return False