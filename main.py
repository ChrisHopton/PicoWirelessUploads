import network
import socket
import time
import _thread

# WiFi credentials
SSID = "Lotion"
PASSWORD = "Mypassword"
PORT = 8000

# Global variables for script management
current_script_thread = None
script_lock = _thread.allocate_lock()
stop_current_script = False

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print('Connecting to WiFi...')
        wlan.connect(SSID, PASSWORD)
        while not wlan.isconnected():
            time.sleep(1)
    print('Connected to WiFi')
    print('IP:', wlan.ifconfig()[0])
    return wlan

def run_script(code):
    """Execute the uploaded script in a thread with proper cleanup"""
    global stop_current_script
    try:
        print("Starting script execution...")
        # Create a new namespace for the script
        namespace = {'stop_execution': lambda: stop_current_script}
        
        # Inject the check_stop function into the script
        injected_code = (
            "def check_stop():\n"
            "    if stop_execution():\n"
            "        raise SystemExit('Script stopped')\n\n" +
            code
        )
        
        # Compile the code
        compiled_code = compile(injected_code, 'uploaded_script.py', 'exec')
        
        # Execute in the new namespace
        exec(compiled_code, namespace)
        print("Script execution completed")
        
    except SystemExit as e:
        print(f"Script stopped: {e}")
    except Exception as e:
        print(f"Script execution error: {e}")
    finally:
        with script_lock:
            global current_script_thread
            current_script_thread = None
            stop_current_script = False
        print("Script thread cleaned up.")

def stop_running_script():
    """Safely stop the currently running script"""
    global stop_current_script, current_script_thread
    
    if current_script_thread is not None:
        print("Stopping current script...")
        stop_current_script = True
        # Wait for the script to acknowledge the stop signal
        timeout = 10  # seconds
        start_time = time.time()
        while current_script_thread is not None and (time.time() - start_time) < timeout:
            time.sleep(0.1)
        if current_script_thread is not None:
            print("Warning: Script did not terminate within the timeout period.")
        else:
            print("Script terminated successfully.")
        return True
    return False

def handle_file_upload(conn, content_length):
    """Handle file upload with chunked reading"""
    global current_script_thread
    
    print("Starting file upload handling...")
    
    file_content = b''
    file_started = False
    total_read = 0
    
    while total_read < content_length:
        try:
            chunk = conn.recv(256)
            if not chunk:
                break
                
            total_read += len(chunk)
            
            if not file_started:
                if b'\r\n\r\n' in chunk:
                    file_started = True
                    _, content = chunk.split(b'\r\n\r\n', 1)
                    file_content = content
                continue
            
            file_content += chunk
            
        except Exception as e:
            print(f"Error reading chunk: {e}")
            break
    
    if file_content:
        try:
            # Find the end boundary and remove it
            if b'\r\n--' in file_content:
                file_content = file_content.split(b'\r\n--')[0]
            
            # Convert to text and clean up
            content = file_content.decode('utf-8').strip()
            
            # Stop any currently running script
            if stop_running_script():
                # Wait until the script has fully stopped
                while current_script_thread is not None:
                    time.sleep(0.1)
            
            # Acquire the script lock before starting a new thread
            with script_lock:
                # Save the uploaded script
                print("Saving file...")
                with open('uploaded_script.py', 'w') as f:
                    f.write(content)
                
                # Start the new script in a new thread
                print("Starting new script thread...")
                current_script_thread = _thread.start_new_thread(run_script, (content,))
                print("Script started in new thread.")
            
            return True
            
        except Exception as e:
            print(f"Error processing file: {e}")
            return False
    
    print("No file content received.")
    return False

def read_until(conn, delimiter, buffer_size=256):
    """Read from connection until delimiter is found"""
    data = b''
    while delimiter not in data:
        try:
            chunk = conn.recv(buffer_size)
            if not chunk:
                break
            data += chunk
        except Exception as e:
            print(f"Read error: {e}")
            break
    return data

def handle_request(conn):
    try:
        conn.settimeout(5.0)
        request = read_until(conn, b'\r\n\r\n')
        if not request:
            return
            
        request_head = request.decode('utf-8')
        print("Request type:", request_head.split()[0] if request_head else "Unknown")
        
        if request_head.startswith('POST'):
            content_length = 0
            for line in request_head.split('\r\n'):
                if 'Content-Length: ' in line:
                    content_length = int(line.split('Content-Length: ')[1])
                    break
            
            if content_length > 0:
                print(f"Processing upload, content length: {content_length}")
                success = handle_file_upload(conn, content_length)
                
                if success:
                    response = (
                        "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n"
                        "<html><body><h2>File uploaded and script started!</h2>"
                        "<p>The script is now running in the background.</p>"
                        "<p><a href='/'>Upload another file</a></p></body></html>"
                    )
                else:
                    response = (
                        "HTTP/1.1 400 Bad Request\r\nContent-Type: text/html\r\n\r\n"
                        "<html><body><h2>Error processing file</h2>"
                        "<p><a href='/'>Try again</a></p></body></html>"
                    )
            else:
                response = (
                    "HTTP/1.1 400 Bad Request\r\nContent-Type: text/html\r\n\r\n"
                    "<html><body><h2>Invalid upload</h2></body></html>"
                )
                
        else:
            if 'favicon.ico' in request_head:
                response = "HTTP/1.1 404 Not Found\r\n\r\n"
            else:
                response = (
                    "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n"
                    "<html>"
                    "<head>"
                        "<title>Pico W Python File Upload</title>"
                        "<style>"
                            "body { font-family: Arial, sans-serif; margin: 20px; }"
                            ".container { max-width: 800px; margin: 0 auto; }"
                            ".upload-form { margin: 20px 0; }"
                            ".file-input { margin: 10px 0; }"
                        "</style>"
                    "</head>"
                    "<body>"
                        "<div class='container'>"
                            "<h1>Upload Python File</h1>"
                            "<form class='upload-form' action='/' method='POST' enctype='multipart/form-data'>"
                                "<p>Select a Python file (.py) to upload and execute:</p>"
                                "<input class='file-input' type='file' name='file' accept='.py' required><br>"
                                "<input type='submit' value='Upload and Run'>"
                            "</form>"
                            "<p>Note: Uploading a new file will replace any currently running script.</p>"
                        "</div>"
                    "</body>"
                    "</html>"
                )
        
        conn.send(response.encode())
    except Exception as e:
        print(f"Error in handle_request: {e}")
        try:
            error_response = (
                "HTTP/1.1 500 Internal Server Error\r\nContent-Type: text/html\r\n\r\n"
                f"<html><body><h2>Server Error: {str(e)}</h2></body></html>"
            )
            conn.send(error_response.encode())
        except:
            pass
    finally:
        conn.close()
        print("Connection closed")

def serve():
    s = socket.socket()
    s.bind(('', PORT))
    s.listen(1)
    print(f'Listening on port {PORT}...')
    
    while True:
        try:
            conn, addr = s.accept()
            print(f'\nNew connection from {addr}')
            handle_request(conn)
        except Exception as e:
            print(f"Error accepting connection: {e}")

def main():
    connect_wifi()
    try:
        serve()
    except Exception as e:
        print(f"Server error: {e}")

if __name__ == '__main__':
    main()
