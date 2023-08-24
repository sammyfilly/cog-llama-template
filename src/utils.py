import os
import subprocess
import random
import time
import typing as tp
import asyncio

def get_env_var_or_default(var_name,default_value):
    """
    Attempts to load a global variable from an environment variable.
    
    Args:
    - var_name (str): Name of the global variable.
    - default_value: The default value to use if the environment variable doesn't exist or its length is 0.
    
    Returns:
    - value: The value from the environment variable or the default value.
    """
    env_value = os.environ.get(var_name, "")

    # Check if the environment variable exists and is not empty
    if len(env_value) > 0:
        return env_value
    else:
        return default_value


class Logger:
    def __init__(self, marker: str = 'predict-timings'):
        self.marker = marker + "%s" % random.randint(0, 1000000)
        self.start = time.time()
        self.last = self.start
    
    def log(self, *args):
        current_time = time.time()
        elapsed_since_start = current_time - self.start
        elapsed_since_last_log = current_time - self.last
        
        message = " ".join(str(arg) for arg in args)
        timings = f"{elapsed_since_start:.2f}s since start, {elapsed_since_last_log:.2f}s since last log"
        
        print(f"{self.marker}: {message} - {timings}")
        self.last = current_time


def check_files_exist(remote_files, local_path):
    # Get the list of local file names
    local_files = os.listdir(local_path)
    
    # Check if each remote file exists in the local directory
    missing_files = [file for file in remote_files if file not in local_files]
    
    return missing_files

async def download_file_with_pget(remote_path, dest_path):
    # Create the subprocess
    print("Downloading ", remote_path)
    process = await asyncio.create_subprocess_exec(
        'pget', remote_path, dest_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    # Wait for the subprocess to finish
    stdout, stderr = await process.communicate()

    # Print what the subprocess output (if any)
    if stdout:
        print(f'[stdout]\n{stdout.decode()}')
    if stderr:
        print(f'[stderr]\n{stderr.decode()}')

async def download_files_with_pget(remote_path, path, files):
    await asyncio.gather(*(download_file_with_pget(f"{remote_path}/{file}", f"{path}/{file}") for file in files))

    # # Run the bash script for each missing file 
    # process = subprocess.Popen(["./src/download-with-pget.sh", remote_path, path, *files])
    # process.wait()

def maybe_download_with_pget(
    path, 
    remote_path: tp.Optional[str] = None, 
    remote_filenames: tp.Optional[tp.List[str]] = [],
    logger: tp.Optional[Logger] = None):
    """
    Downloads files from remote_path to path if they are not present in path. File paths are constructed 
    by concatenating remote_path and remote_filenames. If remote_path is None, files are not downloaded.

    Args:
        path (str): Path to the directory where files should be downloaded
        remote_path (str): Path to the directory where files should be downloaded from
        remote_filenames (List[str]): List of file names to download
        logger (Logger): Logger object to log progress
    
    Returns:
        path (str): Path to the directory where files were downloaded
    
    Example:

        maybe_download_with_pget(
            path="models/roberta-base",
            remote_path="gs://my-bucket/models/roberta-base",
            remote_filenames=["config.json", "pytorch_model.bin", "tokenizer.json", "vocab.json"],
            logger=logger
        )
    """
    if remote_path:
        remote_path = remote_path.rstrip("/")

        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            missing_files = remote_filenames
        else:
            local_files = os.listdir(path)
            missing_files = check_files_exist(remote_filenames, path)

        if len(missing_files) > 0:
            print('Downloading weights...')
            st = time.time()
            if logger:
                logger.info(f"Downloading {missing_files} from {remote_path} to {path}")
            asyncio.run(download_files_with_pget(remote_path, path, missing_files))
            if logger:
                logger.info(f"Finished download")
            print(f"Finished download in {time.time() - st:.2f}s")


    return path
#  [self.tokenizer.encode(seq, add_special_tokens=False) for seq in stop_sequences]

class StreamingTokenStopSequenceHandler:
    def __init__(self, stop_sequences_token_ids: tp.List[str] = None, eos_token_id: int = None):
        self.stop_sequences_token_ids = stop_sequences_token_ids
        self.eos_token_id = eos_token_id

        if stop_sequences_token_ids:
            self.stop_sequences_token_ids = stop_sequences_token_ids
            self.stop_sequence_tracker = [0] * len(self.stop_sequences_token_ids)
            self.cache = []

    def process(self, token_id):
            token_in_stop_sequence = False
            stop_sequence_tracker = self.stop_sequence_tracker.copy()

            # Iterate through each stop sequence
            for idx, stop_sequence in enumerate(self.stop_sequences_token_ids):
                    # If token matches the next token in the stop sequence
                    if token_id == stop_sequence[stop_sequence_tracker[idx]]:
                        token_in_stop_sequence = True
                        stop_sequence_tracker[idx] += 1

                        # If we completed a stop sequence
                        if stop_sequence_tracker[idx] == len(stop_sequence):
                            # Clear the cache and reset all trackers
                            self.cache.clear()
                            stop_sequence_tracker = [0] * len(self.stop_sequences_token_ids)
                            yield self.eos_token_id

                    # If token doesn't match the next token in the stop sequence
                    else:
                        # Reset the tracker for that stop token sequence
                        stop_sequence_tracker[idx] = 0    

            if not token_in_stop_sequence:
                # If token doesn't continue a stop sequence, yield all cached tokens and the current token

                tokens_to_yield = self.cache + [token_id]
                self.cache.clear()
                for token in tokens_to_yield:
                    yield token
            else:
                # If we've reset a stop token counter, we need to yield cached tokens and then clear the cache
                for i,j in zip(stop_sequence_tracker, self.stop_sequence_tracker):
                    if i < j:
                        for token in self.cache:
                            yield token
                        self.cache.clear()
                
                # Then we need to update the tracker and cache the current token
                self.stop_sequence_tracker = stop_sequence_tracker
                self.cache.append(token_id)    

    def __call__(self, token_id):
        if self.stop_sequences_token_ids:
            yield from self.process(token_id)

        else:
            yield token_id

    def finalize(self):
        if self.cache:
            yield from self.cache
            self.cache.clear()




class StreamingTextStopSequenceHandler:
    def __init__(self, stop_sequences: tp.List[str] = None, eos_token: str = None):
        self.stop_sequences = stop_sequences
        self.eos_token = eos_token
        self.cache = []

        if stop_sequences:
            self.stop_sequence_tracker = [0] * len(self.stop_sequences)
            self.stop_sequence_lens = [len(seq) for seq in self.stop_sequences]

    def get_match_length(self, text: str, stop_sequence: str):
            """
            Checks if the end of the provided text matches the beginning of any stop sequence.
            Returns the length of the matched stop sequence if it exists, otherwise returns 0.
            """
            matched_len = 0
            for i in range(1, len(stop_sequence) + 1):
                # Check if the end of the text matches the start of the stop_sequence
                if text.endswith(stop_sequence[:i]):
                    matched_len = i
            if matched_len:
                return matched_len
            return 0

    def process(self, token):
            partial_match = False
            stop_sequence_tracker = self.stop_sequence_tracker.copy()

            # Iterate through each stop sequence
            text = ''.join(self.cache) + token
            for idx, stop_sequence in enumerate(self.stop_sequences):
                    # If token matches the next token in the stop sequence
                    match_length = self.get_match_length(text, stop_sequence)
                    if match_length:
                        # If we've completed the stop sequence
                        if match_length == self.stop_sequence_lens[idx]:
                            self.cache.clear()
                            stop_sequence_tracker = [0] * len(self.stop_sequences)
                            yield self.eos_token
                        else:
                            partial_match = True
                            # If we've matched more characters than before, update the tracker
                            if match_length > stop_sequence_tracker[idx]:
                                stop_sequence_tracker[idx] = match_length
                            else:
                                # Reset the tracker for that sequence
                                stop_sequence_tracker[idx] = 0
                            
                    # If token doesn't match the next token in the stop sequence
                    else:
                        # Reset the tracker for that stop token sequence
                        stop_sequence_tracker[idx] = 0    

            if not partial_match:
                # If token doesn't match a stop sequence, yield all cached tokens and the current token
                self.cache.clear()
                yield text

            else:
                # If we've reset a stop token counter, we need to yield cached tokens and then clear the cache
                for i,j in zip(stop_sequence_tracker, self.stop_sequence_tracker):
                    if i < j:
                        yield ''.join(self.cache)
                        self.cache.clear()

                # Then we need to update the tracker and cache the current token
                self.stop_sequence_tracker = stop_sequence_tracker
                self.cache.append(token)    

    def __call__(self, token):
        if self.stop_sequences:
            yield from self.process(token)

        else:
            yield token

    def finalize(self):
        if self.cache:
            yield from self.cache
            self.cache.clear()

   