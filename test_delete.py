import requests

# Сначала создай видео
r1 = requests.post("http://localhost:8000/api/v1/videos/", 
                   json={"title": "ToDelete", "visibility": "public"})
print("Create:", r1.status_code, r1.json())

# Потом удали
video_id = r1.json()["id"]
r2 = requests.delete(f"http://localhost:8000/api/v1/videos/{video_id}")
print("Delete:", r2.status_code, r2.text)
