from flask import Flask, render_template, request, send_file
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from pdf2docx import Converter
import requests
from PIL import Image
import pytesseract
import io
import os
import time
import threading
import pandas as pd 
import zipfile

app = Flask(__name__)

app.config['UPLOAD_FOLDER'] = 'uploads'

# Dictionary to store upload timestamps
file_upload_times = {}


def compress_image(image_path, output_path, quality=85):
    try:
        img = Image.open(image_path)

        # Check image format
        if img.format == 'JPEG':
            # For JPEG, use the quality parameter
            img.save(output_path, 'JPEG', quality=quality)
        elif img.format == 'PNG':
            # For PNG, use a different approach (quantization)
            img = img.convert("P", palette=Image.ADAPTIVE, colors=256)
            img.save(output_path, 'PNG', optimize=True)

    except Exception as e:
        print(f"Error compressing image: {str(e)}")

@app.route('/compress_image')
def compress_images_page():
    return render_template('compress_image.html')

@app.route('/upload_and_compress', methods=['POST'])
def upload_and_compress():
    if request.method == 'POST':
        quality = int(request.form['quality'])
        uploaded_files = request.files.getlist('images')

        if uploaded_files:
            # Check if only one image is selected
            if len(uploaded_files) == 1:
                # Only one image, provide it as a download without zipping
                uploaded_file = uploaded_files[0]
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], uploaded_file.filename)
                uploaded_file.save(image_path)

                compressed_filename = f"compressed_{uploaded_file.filename}"
                compressed_path = os.path.join(app.config['UPLOAD_FOLDER'], compressed_filename)
                compress_image(image_path, compressed_path, quality=quality)

                # Provide the compressed image as a download
                return send_file(compressed_path, as_attachment=True, download_name=compressed_filename)
            
            else:
                # Multiple images, create a zip file
                # Create a temporary directory to store compressed images
                temp_dir = 'temp_images'
                os.makedirs(temp_dir, exist_ok=True)

                # Compress each uploaded image
                compressed_files = []
                for uploaded_file in uploaded_files:
                    image_path = os.path.join(app.config['UPLOAD_FOLDER'], uploaded_file.filename)
                    uploaded_file.save(image_path)

                    compressed_filename = f"compressed_{uploaded_file.filename}"
                    compressed_path = os.path.join(temp_dir, compressed_filename)
                    compress_image(image_path, compressed_path, quality=quality)

                    compressed_files.append(compressed_path)

                # Create a zip file containing all compressed images
                zip_filename = 'compressed_images.zip'
                zip_path = os.path.join(app.config['UPLOAD_FOLDER'], zip_filename)
                with zipfile.ZipFile(zip_path, 'w') as zip_file:
                    for compressed_file in compressed_files:
                        zip_file.write(compressed_file, os.path.basename(compressed_file))

                # Provide the zip file as a download
                return send_file(zip_path, as_attachment=True, download_name=zip_filename)

    return render_template('compress_image.html')


def cleanup_files(pdf_path, word_path):
    # Delete the PDF and Word files
    os.remove(pdf_path)
    os.remove(word_path)



def html_table_to_csv(html_content):
    # Use BeautifulSoup to parse HTML content
    soup = BeautifulSoup(html_content, 'html.parser')

    # Find the HTML table
    table = soup.find('table')

    # Use pandas to read the HTML table and convert it to CSV
    df = pd.read_html(str(table), header=0)[0]
    csv_content = df.to_csv(index=False)

    return csv_content

@app.route('/html_to_csv', methods=['GET', 'POST'])
def html_to_csv():
    if request.method == 'POST':
        html_content = request.form.get('html_content')
        if html_content:
            csv_content = html_table_to_csv(html_content)

            # Provide the CSV file as a download
            return send_file(io.BytesIO(csv_content.encode()), as_attachment=True, download_name='table.csv')
    else:
        # Your code for handling GET requests
        return render_template('html_to_csv.html')

    return render_template('html_to_csv.html')

@app.route('/pdf-to-doc')
def pdf_to_doc():
    return render_template('pdf-to-doc.html')

@app.route('/convert', methods=['POST'])
def convert():
    if request.method == 'POST':
        # Check if the POST request has the file part
        if 'file' not in request.files:
            return render_template('pdf-to-doc.html', error='No file part')

        file = request.files['file']

        # Check if the file is selected
        if file.filename == '':
            return render_template('pdf-to-doc.html', error='No file selected')

        # Check if the file is a PDF
        if file.filename.endswith('.pdf'):
            # Convert PDF to Word
            word_filename = file.filename.replace('.pdf', '.docx')
            pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            word_path = os.path.join(app.config['UPLOAD_FOLDER'], word_filename)

            file.save(pdf_path)

            cv = Converter(pdf_path)
            cv.convert(word_path)
            cv.close()

            # Store the current timestamp for file cleanup
            file_upload_times[word_filename] = time.time()

            # Start a thread to schedule file cleanup after 1 minute
            cleanup_thread = threading.Thread(target=schedule_cleanup, args=(pdf_path, word_path))
            cleanup_thread.start()

            return send_file(word_path, as_attachment=True, download_name=word_filename)

        else:
            return render_template('pdf-to-doc.html', error='Invalid file format. Please upload a PDF file.')
        
def schedule_cleanup(pdf_path, word_path):
    word_filename = os.path.basename(word_path)
    upload_time = file_upload_times.get(word_filename, 0)

    # Wait for 1 minute after the file upload time
    while time.time() - upload_time < 60:
        time.sleep(1)

    cleanup_files(pdf_path, word_path)


def bfs_fetch_urls(start_url, allowed_domain, max_urls=1000):
    visited_urls = set()
    unique_urls = set()
    queue = [start_url]
    urls_fetched = 0

    while queue and urls_fetched < max_urls:
        current_url = queue.pop(0)

        # Skip if the URL has already been visited
        if current_url in visited_urls:
            continue

        try:
            response = requests.get(current_url)
            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract all anchor tags
            anchor_tags = soup.find_all('a', href=True)

            for anchor_tag in anchor_tags:
                href = anchor_tag['href']
                resolved_url = urljoin(start_url, href)

                # Check if the resolved URL starts with the allowed domain
                if resolved_url.startswith(allowed_domain):
                    unique_urls.add(resolved_url)

                    # Add the resolved URL to the queue if it hasn't been visited
                    if resolved_url not in visited_urls:
                        queue.append(resolved_url)
                        urls_fetched += 1

            
        except Exception as e:
            print(f"Error fetching URLs for {current_url}: {str(e)}")

        visited_urls.add(current_url)

    return list(unique_urls)


def extract_text_from_image(image_content):
    try:
        img = Image.open(io.BytesIO(image_content))
        
        # Specify the path to the Tesseract executable
        pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
        
        text = pytesseract.image_to_string(img)
        return text
    except Exception as e:
        print(f"Error extracting text from image: {str(e)}")
        return None

@app.route('/', methods=['GET', 'POST'])
def index():
    urls = []

    if request.method == 'POST':
        start_url = request.form.get('url')
        if start_url:
            allowed_domain = urlparse(start_url).scheme + '://' + urlparse(start_url).netloc
            urls = bfs_fetch_urls(start_url, allowed_domain)

            # For demonstration, add a delay to simulate fetching
            # time.sleep(5)

    return render_template('index.html', urls=urls)

@app.route('/fetch_urls', methods=['POST'])
def fetch_urls():
    if request.method == 'POST':
        start_url = request.form.get('url')
        if start_url:
            allowed_domain = urlparse(start_url).scheme + '://' + urlparse(start_url).netloc
            urls = bfs_fetch_urls(start_url, allowed_domain)

            # For demonstration, add a delay to simulate fetching
            # time.sleep(5)

            return {'urls': urls}

    return render_template('index.html')

@app.route('/image_to_text', methods=['GET', 'POST'])
def image_to_text():
    extracted_text = ""

    if request.method == 'POST':
        image_file = request.files['image']

        if image_file:
            image_content = image_file.read()
            extracted_text = extract_text_from_image(image_content)

    return render_template('image_to_text.html', extracted_text=extracted_text)



@app.route('/jpg_to_png')
def jpg_to_png():
    return render_template('jpg_to_png.html')

@app.route('/convert_jpg_to_png', methods=['POST'])
def convert_jpg_to_png():
    if request.method == 'POST':
        jpg_file = request.files['jpg_file']

        if jpg_file:
            # Save the JPG file
            jpg_path = os.path.join(app.config['UPLOAD_FOLDER'], jpg_file.filename)
            jpg_file.save(jpg_path)

            # Convert JPG to PNG
            png_filename = jpg_file.filename.replace('.jpg', '.png')
            png_path = os.path.join(app.config['UPLOAD_FOLDER'], png_filename)

            img = Image.open(jpg_path)
            img.save(png_path, 'PNG')

            # Provide the PNG file as a download
            return send_file(png_path, as_attachment=True, download_name=png_filename)

    return render_template('jpg_to_png.html')

if __name__ == '__main__':
    app.run(debug=True)