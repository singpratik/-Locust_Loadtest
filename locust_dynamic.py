import os
import random
import time
import logging
import csv
import requests
import urllib3
from locust import HttpUser, task, between
import json
import traceback

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def load_user_credentials(file_path):
    """Load user credentials from a CSV file."""
    credentials = []
    try:
        with open(file_path, mode='r') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if "Email" in row and "Password" in row:
                    credentials.append({"email": row["Email"], "password": row["Password"]})
                else:
                    logger.warning(f"Skipping row due to missing Email or Password: {row}")
    except FileNotFoundError:
        logger.error(f"Credentials file not found: {file_path}")
    except Exception as e:
        logger.error(f"Error reading CSV file: {str(e)}")
    
    if not credentials:
        logger.error("No valid user credentials found. Please check your CSV file.")
    
    return credentials

def get_credentials_path():
    """Get the path to the user credentials CSV."""
    potential_paths = [
        '/Users/pratiksingh/Desktop/Interview_automation/Interview_load/user.csv',
        os.path.join(os.path.dirname(__file__), 'user_cred.csv'),
        'user_cred.csv'
    ]
    
    for path in potential_paths:
        if os.path.exists(path):
            return path
    
    raise FileNotFoundError("Could not find user_cred.csv file")

# Load user credentials
USER_CREDENTIALS = load_user_credentials(get_credentials_path())

class InterviewUser(HttpUser):
    wait_time = between(20, 60)
    host = "https://api-uat-us-candidate.vmock.dev"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.access_token = None
        self.current_interview_id = None
        self.question_data = {}
        self.user_credentials = None
        self.current_uid = None
        self.available_uids = []
        self.current_uid_index = 0
        self.interview_data = {}  # Added to fix missing attribute
        
        if not USER_CREDENTIALS:
            raise ValueError("No user credentials available for load testing")

    def on_start(self):
        """Log in to the system."""
        for _ in range(100):
            self.user_credentials = random.choice(USER_CREDENTIALS)
            if self.login():
                break
            logger.warning("Login attempt failed. Retrying...")
            time.sleep(2)
        else:
            logger.error("Failed to login after multiple attempts")
            self.environment.runner.quit()

    @task(1)
    def execute_interview_flow(self):
        """Execute the complete interview flow with enhanced logging."""
        if not self.access_token:
            logger.error("Not logged in - skipping interview flow")
            return

        # Create mock interview with new payload
        if not self.create_mock_interview():
            logger.error("Failed to create mock interview - aborting flow")
            return

        if not self.start_calibration() or not self.start_interview():
            logger.error("Failed to start calibration or interview - aborting flow")
            return

        logger.info(f"Starting interview processing with {len(self.available_uids)} UIDs")
        
        # Process each UID with detailed logging
        for uid in self.available_uids:
            self.current_uid = uid
            logger.info(f"\n{'='*50}\nProcessing UID: {uid}\n{'='*50}")

            if not self.process_next_question(uid):  # Fixed: Removed self from arguments
                logger.error(f"Failed to process question for UID {uid}")
                return

            if not self.duration_clip_with_retry(uid):
                logger.error(f"Failed to process duration clip for UID {uid}")
                return

            logger.info(f"Successfully processed UID {uid}")
            time.sleep(3)  # Brief pause between questions

        # Final interview completion
        if not self.end_interview():
            logger.error("Failed to properly end interview")
            return

        logger.info(f"\n{'*'*50}\nInterview completed successfully!\nInterview ID: {self.current_interview_id}\n{'*'*50}")

    def login(self):
        """Perform login and return True if successful."""
        if not self.user_credentials or not isinstance(self.user_credentials, dict):
            logger.error("Invalid user credentials")
            return False
            
        payload = {
            "email": self.user_credentials.get("email", ""),
            "password": self.user_credentials.get("password", ""),
            "provider": "email"
        }
        logger.info(f"Attempting to login with email: {self.user_credentials.get('email')}")

        with self.client.post(
            "/dashboard-api-accounts/api/v1/login/common",
            json=payload,
            catch_response=True,
            name="/login"
        ) as response:
            if response.status_code == 200:
                self.access_token = response.json().get('access_token')
                logger.info(f"Login successful for user: {self.user_credentials.get('email')}")
                return True
            logger.error(f"Login failed for user: {self.user_credentials.get('email')} with status {response.status_code}")
            return False

    def create_mock_interview(self):
        """Create mock interview with updated payload and better error handling."""
        if not self.access_token:
            logger.error("No access token available")
            return False

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "template_id": 8000,
            "selected_questions": [
                202965, 202966, 202967, 202968, 202969,
                202970, 202971, 202972, 202973, 202974,
                202975, 202976, 202977, 202978, 202979,
                202980, 202981, 202982
            ],
            "csrf_token": "1IIml0aWEAB0eflM7LzE55gJXboT0sZEJ2EGrogu"
        }

        logger.info("Creating mock interview with payload:")
        logger.info(json.dumps(payload, indent=2))

        with self.client.post(
            "/interviews-api/v1/mock-interview/create",
            json=payload,
            headers=headers,
            catch_response=True,
            name="/mock-interview/create"
        ) as response:
            if response.status_code in [200, 201]:
                response_data = response.json()
                self.current_interview_id = response_data.get('interview_id')
                self.question_data = response_data.get('question_data', {})
                self.available_uids = sorted([str(uid) for uid in self.question_data.keys()])
                
                logger.info(f"Mock interview created successfully. ID: {self.current_interview_id}")
                logger.info(f"Received {len(self.available_uids)} questions")
                return True
            
            logger.error(f"Failed to create mock interview. Status: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False

    def start_calibration(self):
        """Start the calibration."""
        if not self.access_token or not self.current_interview_id:
            logger.error("Missing access token or interview ID")
            return False

        video_file_path = "/Users/pratiksingh/Desktop/No-code-automation-demo-main/TopcoderAutomationDemo/LoadTest/calibration_324456_40000.mkv"
        if not os.path.exists(video_file_path):
            logger.error(f"Calibration video file does not exist at {video_file_path}")
            return False

        with open(video_file_path, "rb") as video_file:
            files = {"clip": (os.path.basename(video_file_path), video_file, "video/x-matroska")}
            payload = {"clip_id": 20000, "interview_id": self.current_interview_id}
            headers = {"Authorization": f"Bearer {self.access_token}"}

            with self.client.post(
                "/interviews-api/v1/interview/calibration",
                data=payload,
                files=files,
                headers=headers,
                catch_response=True,
                name="/interview/calibration"
            ) as response:
                if response.ok:
                    logger.info(f"Calibration started successfully with interview_id: {self.current_interview_id}")
                    return True
                logger.error(f"Failed to start calibration: {response.status_code}")
                return False

    def start_interview(self):
        """Start the interview with the first UID."""
        if not self.access_token or not self.current_interview_id:
            logger.error("Missing access token or interview ID")
            return False

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "clip_id": 20000,
            "interview_id": self.current_interview_id,
            "tentative_duration": 720,
            "interview_type": "mock"
        }

        try:
            with self.client.post(
                "/interviews-api/v1/interview/start",
                json=payload,
                headers=headers,
                catch_response=True,
                name="/interview/start"
            ) as response:
                if response.status_code != 200:
                    logger.error(f"Failed to start interview: {response.status_code} - {response.text}")
                    return False

                response_data = response.json()
                logger.info(f"Interview started successfully with ID: {self.current_interview_id}")
                logger.info(f"Processing first UID: {self.current_uid}")
                
                # Process initial uploads for first UID
                return self.process_current_uid_uploads(response_data)

        except Exception as e:
            logger.error(f"Exception in start_interview: {str(e)}")
            return False
        
    def process_current_uid_uploads(self, response_data):
        """Process uploads for current UID."""
        if not response_data:
            logger.error("No response data provided")
            return False
            
        upload_urls = response_data.get('upload_urls', {})
        video_urls = upload_urls.get('video_urls', [])
        audio_urls = upload_urls.get('audio_chunks_urls', [])

        logger.info(f"Processing uploads for UID {self.current_uid}")
        
        video_directory = "/Users/pratiksingh/Desktop/No-code-automation-demo-main/TopcoderAutomationDemo/LoadTest/mi_clips"
        audio_directory = "/Users/pratiksingh/Desktop/No-code-automation-demo-main/TopcoderAutomationDemo/LoadTest/mi_clips"

        video_files = self.get_local_files(video_directory, ['.mkv', '.mp4'])
        audio_files = self.get_local_files(audio_directory, ['.wav', '.mp3'])

        # Process audio clips
        for i, audio_url in enumerate(audio_urls):
            if i >= len(audio_files):
                logger.warning(f"Not enough audio files. Need {len(audio_urls)}, have {len(audio_files)}")
                return False

            is_last = (i == len(audio_files) - 1)
            if not self.upload_and_process_audio(audio_files[i], audio_url, i, is_last):
                return False

        # Process video clips
        for j, video_url in enumerate(video_urls):
            if j >= len(video_files):
                logger.warning(f"Not enough video files. Need {len(video_urls)}, have {len(video_files)}")
                return False

            if not self.upload_and_process_video(video_files[j], video_url, j):
                return False

        return True

    def get_interview_data(self):
        """
        Get the stored interview data in a structured format
        Returns:
            dict: Formatted interview data including interview_id, question_data, and upload_urls
        """
        return self.interview_data
      
    def get_question_data(self, uid):
        """
        Get data for a specific question by UID
        Args:
            uid (str): Question UID
        Returns:
            dict: Question data or None if not found
        """
        return self.interview_data.get("question_data", {}).get(str(uid))

    def get_local_files(self, directory, extensions):
        """Retrieve a list of files from a directory with specified extensions."""
        files = []
        try:
            if os.path.isdir(directory):
                for file in os.listdir(directory):
                    if any(file.endswith(ext) for ext in extensions):
                        files.append(os.path.join(directory, file))
                logger.info(f"Found files in {directory}: {files}")
            else:
                logger.error(f"{directory} is not a valid directory.")
        except Exception as e:
            logger.error(f"Error accessing directory {directory}: {str(e)}")
        return files
    
    def upload_video_clip(self, file_path, upload_url):
        """Upload video clip to the specified URL"""
        if not os.path.exists(file_path):
            logger.error(f"Video file not found: {file_path}")
            return False
        
        try:
            with open(file_path, 'rb') as video_file:
                response = requests.put(
                    upload_url,
                    data=video_file,
                    headers={"Content-Type": "video/x-matroska"},
                    timeout=60
                )
                if response.status_code in [200, 204]:
                    logger.info(f"Video uploaded successfully: {file_path}")
                    return True
                logger.error(f"Failed to upload video: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Error uploading video: {str(e)}")
            return False

    def upload_audio_clip(self, file_path, upload_url):
        """Upload audio clip to S3 using presigned URL"""
        if not os.path.exists(file_path):
            logger.error(f"Audio file not found: {file_path}")
            return False

        try:
            http = urllib3.PoolManager()
            
            with open(file_path, 'rb') as audio_file:
                response = http.request(
                    'PUT',
                    upload_url,
                    body=audio_file.read(),
                    timeout=urllib3.Timeout(connect=5, read=60),
                    retries=False
                )
            
            if response.status in [200, 204]:
                logger.info(f"Successfully uploaded {file_path}")
                return True
            else:
                logger.error(f"Upload failed. Status: {response.status}")
                return False

        except Exception as e:
            logger.error(f"Error during audio upload: {str(e)}")
            return False 

    def process_audio_clip(self, clip_id, is_last=False):
        """Process uploaded audio clip."""
        if not self.access_token or not self.current_interview_id:
            logger.error("Missing access token or interview ID")
            return False

        if self.current_uid is None:
            logger.error("current_uid is not set. Cannot process audio clip.")
            return False

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

        payload = {
            "interview_id": self.current_interview_id,
            "clip_id": clip_id,
            "uid": str(self.current_uid),  # Ensure uid is string
            "is_last": is_last
        }

        logger.info(f"procesing audio clip for UID{self.current_uid}")
        logger.info(f"Clip id : {clip_id}")
        logger.info(f"is last {is_last}")

        logger.info(f"Processing audio clip with payload: {payload}")

        with self.client.post(
            "/interviews-api/v1/interview/process/audio-clip",
            json=payload,
            headers=headers,
            catch_response=True,
            name="/interview/process/audio-clip"
        ) as response:
            if response.status_code == 200:
                response_data = response.json()
                logger.info(f"Successfully processed audio clip {clip_id}")
                return True
            logger.error(f"Failed to process audio clip {clip_id}: {response.status_code} - {response.text}")
            return False            

    def process_video_clip(self, clip_id):
        """Process uploaded video clip"""
        if not self.access_token or not self.current_interview_id:
            logger.error("Missing access token or interview ID")
            return False

        if self.current_uid is None:
            logger.error("current_uid is not set. Cannot process video clip.")
            return False

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

        payload = {
            "interview_id": self.current_interview_id,
            "clip_id": clip_id,
            "uid": str(self.current_uid)  # Ensure uid is string
        }

        logger.info(f"Processing video clip with payload: {payload}")

        with self.client.post(
            "/interviews-api/v1/interview/process/clip",
            json=payload,
            headers=headers,
            catch_response=True,
            name="/interview/process/clip"
        ) as response:
            if response.status_code == 200:
                response_data = response.json()
                if 'uid' in response_data:
                    self.current_uid = response_data['uid']
                logger.info(f"Successfully processed video clip {clip_id}")
                return True
            logger.error(f"Failed to process video clip {clip_id}: {response.status_code} - {response.text}")
            return False 

    def upload_and_process_audio(self, audio_file, audio_url, clip_id, is_last):
        """Upload and process a single audio clip."""
        if self.upload_audio_clip(audio_file, audio_url):
            if self.process_audio_clip(clip_id, is_last):
                logger.info(f"Successfully processed audio clip {clip_id}")
                return True
            logger.error(f"Failed to process audio clip {clip_id}")
        else:
            logger.error(f"Failed to upload audio {audio_file}")
        return False

    def upload_and_process_video(self, video_file, video_url, clip_id):
        """Upload and process a single video clip."""
        if self.upload_video_clip(video_file, video_url):
            if self.process_video_clip(clip_id):
                logger.info(f"Successfully processed video clip {clip_id}")
                return True
            logger.error(f"Failed to process video clip {clip_id}")
        else:
            logger.error(f"Failed to upload video {video_file}")
        return False     

    def process_next_question(self, uid):
        """Process the next question in sequence."""
        if not self.access_token or not self.current_interview_id:
            logger.error("Missing credentials for processing next question")
            return False

        if self.current_uid_index >= len(self.available_uids):
            logger.error("No more questions to process")
            return False

        # Get the previous and current UID
        prev_uid = self.available_uids[self.current_uid_index - 1] if self.current_uid_index > 0 else None
        
        if prev_uid is None:
            logger.error("No previous UID available")
            return False

        # Prepare the payload
        payload = {
            "prev_uid": int(prev_uid),
            "next_uid": int(uid),
            "interview_id": self.current_interview_id
        }

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        logger.info(f"Processing next question - Prev UID: {prev_uid}, Next UID: {uid}")

        with self.client.post(
            "/interviews-api/v1/mock-interview/question/next",
            json=payload,
            headers=headers,
            catch_response=True,
            name="/mock-interview/question/next"
        ) as response:
            if response.status_code != 200:
                logger.error(f"Next question API failed: {response.status_code} - {response.text}")
                return False

            response_data = response.json()
            
            if not response_data:
                logger.error("Empty response data from next question API")
                return False

            # Process the uploads for the current question
            if not self.process_current_uid_uploads(response_data):
                logger.error("Failed to process uploads for current UID")
                return False

            logger.info(f"Successfully processed next question for UID {uid}")
            return True
        
    def duration_clip_with_retry(self, uid):
        """Call duration-clip API with retries for a specific UID."""
        max_retries = 3
        retry_delay = 5  # seconds
        
        for attempt in range(max_retries):
            try:
                if not self.access_token:
                    logger.error("Missing access token")
                    return False

                headers = {
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json"
                }

                # Ensure uid is converted to int safely
                try:
                    uid_int = int(uid)
                except (ValueError, TypeError):
                    logger.error(f"Invalid UID format: {uid}")
                    return False

                payload = {
                    "uid": uid_int,
                    "clip_count": 24,
                    "duration": 120
                }

                logger.info(f"Calling duration-clip API for UID {uid} (Attempt {attempt + 1}/{max_retries})")
                logger.info(f"Payload: {json.dumps(payload, indent=2)}")

                with self.client.post(
                    "/interviews-api/v1/interview/duration-clip",
                    json=payload,
                    headers=headers,
                    catch_response=True,
                    name="/interview/duration-clip"
                ) as response:
                    if response.status_code in [200, 204]:
                        logger.info(f"Successfully processed duration clip for UID {uid}")
                        return True
                    else:
                        logger.error(f"Duration-clip API failed for UID {uid}: {response.status_code} - {response.text}")
                        if attempt < max_retries - 1:
                            logger.info(f"Retrying in {retry_delay} seconds...")
                            time.sleep(retry_delay)
                            continue
                        return False

            except Exception as e:
                logger.error(f"Error in duration-clip API for UID {uid}: {str(e)}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                return False

        logger.error(f"All duration-clip API attempts failed for UID {uid}")
        return False   

    def end_interview(self):
        """End the interview with improved handling."""
        if not self.access_token or not self.current_interview_id or not self.current_uid:
            logger.error("Missing access token, interview ID, or current UID")
            return False

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "interview_id": self.current_interview_id,
            "uid": str(self.current_uid)  # Ensure uid is string
        }

        logger.info(f"Attempting to end interview {self.current_interview_id}")
        
        with self.client.post(
            "/interviews-api/v1/interview/end",
            json=payload,
            headers=headers,
            catch_response=True,
            name="/interview/end"
        ) as response:
            if response.status_code not in [200, 204]:
                logger.error(f"Failed to end interview: {response.status_code} - {response.text}")
                return False
                    
            logger.info(f"Successfully ended interview: {self.current_interview_id}")
            time.sleep(10)  # Wait for end processing to initialize
            
            # Now check result status until all UIDs are processed
            return self.check_result_status()

    def check_result_status(self):
        """Check and monitor the result status until all values are successful."""
        if not self.access_token or not self.current_interview_id:
            logger.error("Missing access token or interview ID")
            return False

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        max_attempts = 180  # 30 minutes total with 10s interval
        attempt = 0
        interval = 10  # Seconds between checks
        initial_delay = 30  # Initial delay to allow processing to start

        # Define the fields to monitor
        fields_to_monitor = ["categories", "praat", "post_gentle_praat", "video", "convert_video", "skills"]

        logger.info(f"Waiting {initial_delay} seconds for processing to initialize...")
        time.sleep(initial_delay)

        # Create a log file with timestamp
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        log_file_path = f"interview_status_{self.current_interview_id}_{timestamp}.txt"
        
        while attempt < max_attempts:
            try:
                dynamic_param = int(time.time() * 1000)
                url = f"/interviews-api/v1/interview/result-status?interview_id={self.current_interview_id}&_={dynamic_param}"
                
                with self.client.get(
                    url,
                    headers=headers,
                    catch_response=True,
                    name="/interview/result-status"
                ) as response:
                    if response.status_code != 200:
                        logger.error(f"Failed to get result status: {response.status_code} - {response.text}")
                        time.sleep(interval)
                        attempt += 1
                        continue

                    response_data = response.json()
                    all_statuses = response_data.get("all_statuses", {})
                    total_percent = response_data.get("total_percent", 0)
                    is_processed = response_data.get("is_processed", False)

                    # Format timestamp for logging
                    current_time = time.strftime("%Y-%m-%d %H:%M:%S")
                    
                    # Create structured log entry
                    log_entry = f"""
    =================================================
    Time: {current_time}
    Attempt: {attempt + 1}/{max_attempts}
    =================================================
    Interview ID: {self.current_interview_id}
    Total Progress: {total_percent}%
    Is Processed: {is_processed}
    """

                    # Add status for each UID
                    for uid, status in all_statuses.items():
                        log_entry += f"""
    UID: {uid}
    -------------------------------------------------"""
                        
                        # Add each monitored field's status
                        for field in fields_to_monitor:
                            current_status = status.get(field, "not_created")
                            log_entry += f"\n{field}: {current_status}"
                        
                        # Add video processing percentage if available
                        if "video_clips_processed_percentage" in status:
                            log_entry += f"\nvideo_clips_processed_percentage: {status['video_clips_processed_percentage']}%"
                        
                        # Add skip status if available
                        if "is_skipped" in status:
                            log_entry += f"\nis_skipped: {status['is_skipped']}"

                    log_entry += "\n=================================================\n"

                    # Write to log file
                    with open(log_file_path, "a") as log_file:
                        log_file.write(log_entry)

                    # Also log to console
                    logger.info(log_entry)

                    # Check if everything is complete
                    all_complete = all(
                        all(status.get(field) in ["success", "skipped"] 
                        for field in fields_to_monitor
                        for status in all_statuses.values()
                    )

                    if all_complete and total_percent == 100:
                        final_message = f"\nProcessing completed successfully at {current_time}\n"
                        with open(log_file_path, "a") as log_file:
                            log_file.write(final_message)
                        logger.info(final_message)
                        return True

                    time.sleep(interval)
                    attempt += 1

            except Exception as e:
                error_message = f"""
    =================================================
    Time: {time.strftime("%Y-%m-%d %H:%M:%S")}
    Error occurred during status check:
    {str(e)}
    Traceback:
    {traceback.format_exc()}
    =================================================
    """
                with open(log_file_path, "a") as log_file:
                    log_file.write(error_message)
                logger.error(error_message)
                time.sleep(interval)
                attempt += 1
                continue

        timeout_message = f"\nTimeout: Interview processing did not complete within {max_attempts * interval} seconds\n"
        with open(log_file_path, "a") as log_file:
            log_file.write(timeout_message)
        logger.error(timeout_message)
        return False
