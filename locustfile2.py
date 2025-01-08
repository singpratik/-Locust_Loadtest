import os
import random
import time
import logging
import csv
import requests
import urllib3
from locust import HttpUser, task, between
import json
import traceback  # Add this import

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
        '/Users/pratiksingh/Desktop/No-code-automation-demo-main/TopcoderAutomationDemo/LoadTest/user_cred.csv',
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
        self.available_uids =[]
        self.current_uid_index = 0
        
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
        """Execute the complete interview flow with sequential UID processing."""
        if not self.access_token:
            logger.error("Not logged in")
            return

        if not self.create_mock_interview():
            logger.error("Failed to create mock interview")
            return

        if not self.start_calibration() or not self.start_interview():
            logger.error("Failed to start calibration or interview")
            return

        # Log available UIDs
        logger.info(f"Total available UIDs: {len(self.available_uids)}")
        logger.info(f"UIDs to process: {self.available_uids}")

        # Process first UID duration call
        logger.info(f"Processing duration for first UID: {self.current_uid}")
        time.sleep(3)  # Wait for initial processing
        if not self.duration_clip_with_retry(self.current_uid):
            logger.error(f"Failed to process duration clip for first UID {self.current_uid}")
            return

        # Initialize question tracking
        expected_questions = 6
        processed_questions = 1  # We've already processed the first question
        
        # Process remaining questions
        while processed_questions < expected_questions:
            next_uid_index = self.current_uid_index + 1
            
            # Verify we have more UIDs to process
            if next_uid_index >= len(self.available_uids):
                logger.error(f"Ran out of UIDs at index {next_uid_index}. Available UIDs: {self.available_uids}")
                break
                
            # Update current UID and index
            self.current_uid = self.available_uids[next_uid_index]
            self.current_uid_index = next_uid_index
            
            logger.info(f"\nProcessing Question {processed_questions + 1} of {expected_questions}")
            logger.info(f"Current UID: {self.current_uid} (Index: {next_uid_index})")
            
            # Add retry mechanism for processing next question
            max_retries = 3
            for retry in range(max_retries):
                try:
                    if self.process_next_question():
                        # Wait for question processing
                        time.sleep(5)  # Increased wait time
                        
                        # Add retry mechanism for duration clip
                        if self.duration_clip_with_retry(self.current_uid):
                            processed_questions += 1
                            logger.info(f"Successfully processed question {processed_questions} of {expected_questions}")
                            time.sleep(3)  # Wait between questions
                            break
                        else:
                            logger.error(f"Failed to process duration clip for UID {self.current_uid} (Attempt {retry + 1}/{max_retries})")
                    else:
                        logger.error(f"Failed to process question for UID {self.current_uid} (Attempt {retry + 1}/{max_retries})")
                        
                    if retry < max_retries - 1:
                        logger.info(f"Retrying question processing in 5 seconds...")
                        time.sleep(5)
                    else:
                        logger.error(f"Failed to process question after {max_retries} attempts")
                        return False
                        
                except Exception as e:
                    logger.error(f"Exception processing question: {str(e)}")
                    if retry < max_retries - 1:
                        logger.info(f"Retrying after exception in 5 seconds...")
                        time.sleep(5)
                    else:
                        logger.error(f"Failed after {max_retries} attempts due to exceptions")
                        return False

        # Verify all questions were processed
        if processed_questions < expected_questions:
            logger.error(f"Failed to process all questions. Only completed {processed_questions} of {expected_questions}")
            return False

        # End interview and check results
        if not self.end_interview():
            logger.error("Failed to end interview")
            return False

        logger.info(f"Interview flow completed successfully!")
        logger.info(f"Interview ID: {self.current_interview_id}")
        logger.info(f"Total questions processed: {processed_questions} of {expected_questions}")
        return True

        

        
        
            
        

    def login(self):
        """Perform login and return True if successful."""
        payload = {
            "email": self.user_credentials["email"],
            "password": self.user_credentials["password"],
            "provider": "email"
        }
        logger.info(f"Attempting to login with email: {self.user_credentials['email']}")

        with self.client.post(
            "/dashboard-api-accounts/api/v1/login/common",
            json=payload,
            catch_response=True,
            name="/login"
        ) as response:
            if response.status_code == 200:
                self.access_token = response.json().get('access_token')
                logger.info(f"Login successful for user: {self.user_credentials['email']}")
                return True
            logger.error(f"Login failed for user: {self.user_credentials['email']} with status {response.status_code}")
            return False

    def create_mock_interview(self):
        """Create a mock interview and return True if successful."""
        if not self.access_token:
            logger.error("No access token available for creating mock interview")
            return False

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        # Ensure we're requesting exactly 6 questions
        payload = {
            "template_id": 9205,
            "difficulty": "Basic",
            "language": "en",
            "selected_questions": [123385, 123386, 123387, 123388, 123389,123390]  # Exactly 6 questions
        }
        
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
                
                # Store and sort available UIDs
                self.available_uids = sorted([str(uid) for uid in self.question_data.keys()])
                
                # Verify we got all 6 questions
                if len(self.available_uids) != 6:
                    logger.error(f"Expected 6 questions but got {len(self.available_uids)}")
                    return False
                
                # Set initial UID
                self.current_uid = self.available_uids[0]
                self.current_uid_index = 0
                
                logger.info(f"Mock interview created successfully:")
                logger.info(f"Interview ID: {self.current_interview_id}")
                logger.info(f"Available UIDs: {self.available_uids}")
                logger.info(f"Number of questions: {len(self.available_uids)}")
                logger.info(f"Initial UID set to: {self.current_uid}")
                return True
                    
            logger.error(f"Failed to create mock interview: Status {response.status_code}")
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

        
            
# Helper method to access stored interview data
    def get_interview_data(self):
                """
                Get the stored interview data in a structured format
                Returns:
                    dict: Formatted interview data including interview_id, question_data, and upload_urls
                """
                if hasattr(self, 'interview_data'):
                    return self.interview_data
                return None  
      
# Helper method to get specific question data
    def get_question_data(self, uid):
                """
                Get data for a specific question by UID
                Args:
                    uid (str): Question UID
                Returns:
                    dict: Question data or None if not found
                """
                if hasattr(self, 'interview_data'):
                    return self.interview_data["question_data"].get(str(uid))
                return None 


#get_local_files        

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
    

#Hit_upload_video_clip   

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

#Hit_upload_audio_clip       

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

#Hit_process_audio_clip        

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
            "uid": self.current_uid,
            "is_last": is_last
        }

        logger.info(f"procesing audio clip for UID{self.current_uid}")
        logger.info(f"Clip id : {clip_id}")
        logger.info (f"is last {is_last}")

        logger.info(f"Processing audio clip with payload: {payload}")  # Log the payload

        with self.client.post(
            "/interviews-api/v1/interview/process/audio-clip",
            json=payload,
            headers=headers,
            catch_response=True,
            name="/interview/process/audio-clip"
        ) as response:
            if response.status_code == 200:
                response_data = response.json()
                # if 'uid' in response_data:
                #     self.current_uid = response_data['uid']  # Update current_uid
                # Don't update current_uid here as it's managed by the main flow
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
            "uid": self.current_uid
        }

        logger.info(f"Processing video clip with payload: {payload}")  # Log the payload

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



    def process_next_question(self):
        """Process the next question in sequence."""
        if not self.access_token or not self.current_interview_id:
            logger.error("Missing credentials for processing next question")
            return False

        if self.current_uid_index >= len(self.available_uids):
            logger.error("No more questions to process")
            return False

        # Get the previous and current UID
        prev_uid = self.available_uids[self.current_uid_index - 1]
        
        # Prepare the payload
        payload = {
            "prev_uid": int(prev_uid),
            "next_uid": int(self.current_uid),
            "interview_id": self.current_interview_id  # Added interview_id to payload
        }

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        logger.info(f"Processing next question - Prev UID: {prev_uid}, Next UID: {self.current_uid}")

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
            
            # Add validation for response data
            if not response_data:
                logger.error("Empty response data from next question API")
                return False

            # Process the uploads for the current question
            if not self.process_current_uid_uploads(response_data):
                logger.error("Failed to process uploads for current UID")
                return False

            logger.info(f"Successfully processed next question for UID {self.current_uid}")
            return True
        
             
#Hit_duration_clip

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

                # Updated payload values as per actual requirements
                payload = {
                    "uid": int(uid),
                    "clip_count": 24,    # Updated from 2 to 24
                    "duration": 120      # Updated from 10 to 120
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

#Hit_end_interview                

    def end_interview(self):
        """End the interview with improved handling."""
        if not self.access_token or not self.current_interview_id:
            logger.error("Missing access token or interview ID")
            return False

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "interview_id": self.current_interview_id,
            "uid": self.current_uid
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
                            for field in fields_to_monitor)
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