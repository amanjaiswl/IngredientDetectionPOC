from flask import Flask, request, render_template, redirect, url_for, session
import io
import os
import json
import base64
import requests
import boto3
import uuid
from PIL import Image, ImageDraw
os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = 'python'
from google.cloud import vision
from io import BytesIO

app = Flask(__name__)
app.secret_key = b'_5#y2L"F4Q8z\n\xec]/'

s3 = boto3.client('s3', 
                  aws_access_key_id=os.getenv('YOUR_ACCESS_KEY'), 
                  aws_secret_access_key=os.getenv('YOUR_SECRET_KEY'), 
                  region_name=os.getenv('YOUR_REGION_NAME'))


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
            all_results = process_image(image)
            session['results'] = list(all_results)

            # Load the ingredient list from the JSON file
            with open('output.json') as f:
                ingredient_list = json.load(f)["Ingredients_DB"]

            # Check which detected objects are in the ingredient list
            detected_ingredients = []
            for ingredient in ingredient_list:
                if ingredient["displayName"].lower() in all_results or any(name.lower() in all_results for name in ingredient["alternateNames"]):
                    detected_ingredients.append(ingredient["displayName"])

            # Generate a unique file name
            unique_filename = str(uuid.uuid4())

            # Save the image to a temporary file
            temp_file = "/tmp/" + unique_filename + '.jpg'
            image.save(temp_file)

            # Upload the image to S3
            s3.upload_file(temp_file, os.getenv('YOUR_BUCKET_NAME'), unique_filename + '.jpg')

            # Create a JSON file with the results
            results_dict = {
                "all_detected_objects": list(all_results),
                "detected_ingredients": detected_ingredients
            }
            result_json = json.dumps(results_dict)
            result_file = "/tmp/" + unique_filename + '.json'
            with open(result_file, 'w') as f:
                f.write(result_json)

            # Upload the results JSON file to S3
            s3.upload_file(result_file, os.getenv('YOUR_BUCKET_NAME'), unique_filename + '.json')

            return redirect(url_for('results'))
    return render_template('index.html')

            

@app.route('/results')
def results():
    detected_objects = set(session.get('results', []))

    with open('output.json') as f:
        ingredient_list = json.load(f)["Ingredients_DB"]

    with open('output2.json') as f:
        recipe_list = json.load(f)["Recipe_DB"]

    detected_ingredients = []
    ingredient_recipes = {}
    for ingredient in ingredient_list:
        if ingredient["displayName"].lower() in detected_objects or any(name.lower() in detected_objects for name in ingredient["alternateNames"]):
            detected_ingredients.append(ingredient)
            ingredient_recipes[ingredient["displayName"]] = []

    recipe_counts = {}
    for recipe in recipe_list:
        for ingredient in detected_ingredients:
            if ingredient["_id"] in recipe["ingredients"]:
                ingredient_recipes[ingredient["displayName"]].append(recipe["Recipe_Name"])
                if recipe["Recipe_Name"] in recipe_counts:
                    recipe_counts[recipe["Recipe_Name"]]["count"] += 1
                else:
                    recipe_counts[recipe["Recipe_Name"]] = {"count": 1, "image_url": recipe["image_url"]}

    # Prioritize recipes that have the detected ingredient(s) in their name
    for ingredient in detected_ingredients:
        for recipe in recipe_list:
            if ingredient["displayName"].lower() in recipe["Recipe_Name"].lower():
                if recipe["Recipe_Name"] not in recipe_counts:
                    recipe_counts[recipe["Recipe_Name"]] = {"count": 0, "image_url": recipe["image_url"]}
                recipe_counts[recipe["Recipe_Name"]]["count"] += 1

    # Sort the recipes by count and take the top 5
    top_recipes = sorted(recipe_counts.items(), key=lambda x: x[1]["count"], reverse=True)[:3]

    return render_template('results.html', results=detected_objects, ingredients=detected_ingredients, ingredient_recipes=ingredient_recipes, top_recipes=top_recipes)






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