from flask import Flask, request, render_template, redirect, url_for, session
import io
import os
import json
import base64
import requests
from PIL import Image, ImageDraw
os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = 'python'
from google.cloud import vision
from io import BytesIO

app = Flask(__name__)
app.secret_key = b'_5#y2L"F4Q8z\n\xec]/'

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            return 'No file part'
        file = request.files['file']
        if file.filename == '':
            return 'No selected file'
        if file:
            image = Image.open(BytesIO(file.read()))
            result = process_image(image)
            session['results'] = list(result)
            return redirect(url_for('guess'))
    return render_template('index.html')

@app.route('/guess', methods=['GET', 'POST'])
def guess():
    if request.method == 'POST':
        user_input = request.form['guess']
        user_objects = set([obj.strip().lower() for obj in user_input.split(',')])
        session['user_objects'] = list(user_objects)
        return redirect(url_for('results'))
    return render_template('guess.html')

@app.route('/results')
def results():
    user_objects = set(session.get('user_objects', []))
    results = set(session.get('results', []))
    correct_predictions = user_objects.intersection(results)
    score = len(correct_predictions) / len(user_objects) if user_objects else 0
    return render_template('results.html', results=results, score=score, correct_predictions=correct_predictions, total=len(user_objects))


def detect_objects(img):
    """Detect objects in the image.

    Args:
    img: A PIL Image object.
    """
    api_key = os.getenv('YOUR_API_KEY')
    vision_url = f"https://vision.googleapis.com/v1/images:annotate?key={api_key}"

    img_byte_arr = BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('UTF-8')

    request_payload = {
        "requests": [
            {
                "image": {
                    "content": img_base64
                },
                "features": [
                    {
                        "type": "OBJECT_LOCALIZATION"
                    },
                    {
                        "type": "LABEL_DETECTION"
                    }
                ]
            }
        ]
    }

    response = requests.post(vision_url, json=request_payload)
    data = response.json()

    return data

def divide_image(img, n_blocks=(3,3)):
    """Divide the image into equal parts."""
    img_width, img_height = img.size
    part_width = img_width // n_blocks[0]
    part_height = img_height // n_blocks[1]
    parts = []
    for i in range(n_blocks[0]):
        for j in range(n_blocks[1]):
            left = i * part_width
            upper = j * part_height
            right = left + part_width
            lower = upper + part_height
            part = img.crop((left, upper, right, lower))
            parts.append(part)
    return parts

def process_image(img):
    """Process an image: detect objects, crop the image, and detect objects in the cropped images."""
    data = detect_objects(img)
    results = set()

    if 'responses' in data:
        response_data = data['responses'][0]

        if 'localizedObjectAnnotations' in response_data:
            for i, object_annotation in enumerate(response_data['localizedObjectAnnotations']):
                results.add(object_annotation['name'].lower())

                # Crop the image based on the detected object coordinates
                width, height = img.size
                try:
                    vertices = object_annotation['boundingPoly']['normalizedVertices']
                    left = vertices[0]['x'] * width
                    top = vertices[0]['y'] * height
                    right = vertices[2]['x'] * width
                    bottom = vertices[2]['y'] * height
                    cropped_img = img.crop((left, top, right, bottom))

                    # Run the APIs again on the cropped image
                    cropped_data = detect_objects(cropped_img)
                    # Add the detected objects for the cropped image to the results
                    if 'localizedObjectAnnotations' in cropped_data['responses'][0]:
                        for cropped_object_annotation in cropped_data['responses'][0]['localizedObjectAnnotations']:
                            results.add(cropped_object_annotation['name'].lower())

                except (IndexError, KeyError):
                    print("Error: Not all coordinates are available for cropping.")

        if 'labelAnnotations' in response_data:
            for label_annotation in response_data['labelAnnotations']:
                results.add(label_annotation['description'].lower())

    # Divide the original image into nine equal parts
    parts = divide_image(img)
    for i, part in enumerate(parts):

        # Run the APIs on each part
        part_data = detect_objects(part)
        if 'responses' in part_data:
            part_response_data = part_data['responses'][0]

            if 'localizedObjectAnnotations' in part_response_data:
                for part_object_annotation in part_response_data['localizedObjectAnnotations']:
                    results.add(part_object_annotation['name'].lower())

            if 'labelAnnotations' in part_response_data:
                for part_label_annotation in part_response_data['labelAnnotations']:
                    results.add(part_label_annotation['description'].lower())

    return results

if __name__ == '__main__':
    # app.run(debug=True)
    app.run(host='0.0.0.0', port=81)


