import os
import httpx

from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="School Dashboard Service")
Instrumentator().instrument(app).expose(app)

AUTH_URL = os.getenv("AUTH_URL", "http://auth:3001")
ACADEMICS_URL = os.getenv("ACADEMICS_URL", "http://academics:3002")

TIMEOUT = httpx.Timeout(5.0, connect=2.0)

@app.get("/health")
def health():
    return {"status": "ok", "service": "dashboard"}

@app.get("/admin/overview")
async def admin_overview():
    """Aggregated view for school admin. Calls academics service for counts."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            students = await client.get(f"{ACADEMICS_URL}/students")
            teachers = await client.get(f"{ACADEMICS_URL}/teachers")
            sections = await client.get(f"{ACADEMICS_URL}/sections")
            classes  = await client.get(f"{ACADEMICS_URL}/classes")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Upstream unavailable: {e}")

    return {
        "total_students": len(students.json()),
        "total_teachers": len(teachers.json()),
        "total_sections": len(sections.json()),
        "total_classes":  len(classes.json()),
    }

@app.get("/teacher/{teacher_id}/classes")
async def teacher_classes(teacher_id: int):
    """Teacher dashboard: their classes with enrolled student counts."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            teacher_resp = await client.get(f"{ACADEMICS_URL}/teachers/{teacher_id}")
            sections_resp = await client.get(f"{ACADEMICS_URL}/sections")
            students_resp = await client.get(f"{ACADEMICS_URL}/students")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Upstream unavailable: {e}")

    if teacher_resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Teacher not found")

    teacher = teacher_resp.json()
    sections = sections_resp.json()
    students = students_resp.json()

    my_sections = [s for s in sections if s["teacher_id"] == teacher_id]
    for section in my_sections:
        section["students"] = [s for s in students if s["section_id"] == section["id"]]

    return {"teacher": teacher, "sections": my_sections}

@app.get("/student/{student_id}/schedule")
async def student_schedule(student_id: int):
    """Student dashboard: their section and assigned teacher."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            student_resp = await client.get(f"{ACADEMICS_URL}/students/{student_id}")
            if student_resp.status_code == 404:
                raise HTTPException(status_code=404, detail="Student not found")
            student = student_resp.json()

            section_resp = await client.get(f"{ACADEMICS_URL}/sections/{student['section_id']}")
            section = section_resp.json()

            teacher_resp = await client.get(f"{ACADEMICS_URL}/teachers/{section['teacher_id']}")
            teacher = teacher_resp.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Upstream unavailable: {e}")

    return {"student": student, "section": section, "teacher": teacher}

@app.get("/parent/{parent_id}/children")
async def parent_children(parent_id: int):
    """Parent dashboard: all their children and each child's schedule."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            students_resp = await client.get(f"{ACADEMICS_URL}/students")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Upstream unavailable: {e}")

    students = students_resp.json()
    my_children = [s for s in students if s.get("parent_id") == parent_id]

    if not my_children:
        raise HTTPException(status_code=404, detail="No children found for this parent")

    # Fetch schedule for each child
    enriched = []
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for child in my_children:
            section_resp = await client.get(f"{ACADEMICS_URL}/sections/{child['section_id']}")
            section = section_resp.json() if section_resp.status_code == 200 else None
            enriched.append({"child": child, "section": section})

    return {"parent_id": parent_id, "children": enriched}