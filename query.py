import requests
import json
import os

# Get the token from an environment variable
token = os.getenv('your_query_token_here')

if not token:
    print("Token not found!")
else:
    headers = {
         'x-hasura-admin-secret' :token,
        'Content-Type' : 'application/json'
    }

    response = requests.get('https://development-db.hasura.app/api/rest/ingredientlistforobjectdetection', headers=headers)

    # Check if the request was successful
    if response.status_code == 200:
        data = response.json()  # Parse response to JSON
        
        # Write the data to a file instead of printing it
        with open('output.json', 'w') as f:
            json.dump(data, f, indent=4)
        
    else:
        print(f'Request failed with status code {response.status_code}')
        print(f'Error message: {response.text}')  # Print the error 
