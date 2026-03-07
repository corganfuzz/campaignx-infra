import json
import os
import urllib.request
import boto3
from datetime import datetime

def handler(event, context):
    print(f"Received event: {json.dumps(event)}")
    
    raw_bucket = os.environ.get('RAW_BUCKET_NAME')
    series_ids = ["MORTGAGE30US", "MORTGAGE15US", "MORTGAGE5US", "DGS10"]
    
    total_count = 0
    series_metadata = []
    
    try:
        s3 = boto3.client('s3')
        
        for series_id in series_ids:
            url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={api_key}&file_type=json&sort_order=desc&limit=50"
            
            try:
                with urllib.request.urlopen(url) as response:
                    data = json.loads(response.read().decode())
                    observations = data.get('observations', [])
                    
                    for obs in observations:
                        rate = obs['value']
                        date = obs['date']
                        
                        if rate == ".":
                            continue
                            
                        result = {
                            "series_id": series_id,
                            "rate": rate,
                            "date": date,
                            "unit": "percent",
                            "ingestion_date": datetime.now().isoformat()
                        }

                        if raw_bucket:
                            filename = f"mortgage_rates/{series_id}_{date}.json"
                            s3.put_object(
                                Bucket=raw_bucket,
                                Key=filename,
                                Body=json.dumps(result),
                                ContentType='application/json'
                            )
                            total_count += 1
                    
                    latest_val = observations[0]['value'] if observations else "N/A"
                    series_metadata.append(f"{series_id}: {latest_val}%")
                    
            except Exception as e:
                print(f"Error fetching {series_id}: {str(e)}")
                continue

        response_body = {
            'TEXT': {
                'body': f"Massive synchronization complete! Ingested {total_count} records across {len(series_ids)} financial series. Latest snapshots: {', '.join(series_metadata)}."
            }
        }
            
        action_response = {
            'actionGroup': event['actionGroup'],
            'function': event['function'],
            'functionResponse': {
                'responseBody': response_body
            }
        }
        
        # Wrap directly for simplified protocol, or use messageVersion if full protocol
        return {
            "messageVersion": "1.0",
            "response": action_response
        }
            
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            "messageVersion": "1.0",
            "response": {
                'actionGroup': event['actionGroup'],
                'function': event['function'],
                'functionResponse': {
                    'responseBody': {
                        'TEXT': {
                            'body': json.dumps({"error": str(e)})
                        }
                    }
                }
            }
        }
