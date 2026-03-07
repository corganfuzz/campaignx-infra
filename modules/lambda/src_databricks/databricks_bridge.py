import json
import os
import urllib.request
import boto3

def handler(event, context):
    print(f"Received event: {json.dumps(event)}")
    
    # 1. Get Databricks credentials from environment/Secrets Manager
    # For this implementation, we expect these to be passed via environment variables
    db_token = os.environ.get('DATABRICKS_TOKEN')
    db_endpoint_url = os.environ.get('DATABRICKS_ENDPOINT_URL')
    
    # 2. Extract the query from Bedrock Agent's function call
    parameters = event.get('parameters', [])
    query = next((p['value'] for p in parameters if p['name'] == 'query'), "")
    
    if not query:
        return format_response(event, "I couldn't find a query to process. Please provide a mortgage-related question.")

    try:
        # 3. Call Databricks Model Serving
        body = {
            "messages": [
                {
                    "role": "system",
                    "content": "You are the Mortgage Xpert Deep Reasoning Agent. You specialize in complex financial analysis, refinance comparisons, and domain-specific mortgage questions. Provide detailed, analytical responses."
                },
                {
                    "role": "user",
                    "content": query
                }
            ],
            "max_tokens": 1000
        }
        
        req = urllib.request.Request(
            db_endpoint_url,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {db_token}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        
        with urllib.request.urlopen(req) as response:
            res_body = json.loads(response.read().decode())
            answer = res_body['choices'][0]['message']['content']
            
        return format_response(event, answer)
        
    except Exception as e:
        print(f"Error calling Databricks: {str(e)}")
        return format_response(event, f"Error from Databricks Expert: {str(e)}")

def format_response(event, text):
    response_body = {
        'TEXT': {
            'body': text
        }
    }
    
    action_response = {
        'actionGroup': event['actionGroup'],
        'function': event['function'],
        'functionResponse': {
            'responseBody': response_body
        }
    }
    
    return {
        "messageVersion": "1.0",
        "response": action_response
    }
