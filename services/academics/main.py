import os
import time
import random

from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="School Academics Service")
Instrumentator().instrument(app).expose(app)

FAILURE_RATE = float(os.getenv("ACADEMICS_FAILURE_RATE", "0"))
LATENCY_MS = int(os.getenv("ACADEMICS_LATENCY_MS", "0"))

# In-memory seed data. Moves to Postgres in Lab 4.
STUDENTS = [
    {"id": 1, "name": "Alex Smith",     "grade_level": 5, "section_id": 1, "parent_id": 1},
    {"id": 2, "name": "Bella Johnson",  "grade_level": 5, "section_id": 1, "parent_id": 2},
    {"id": 3, "name": "Carlos Mendez",  "grade_level": 6, "section_id": 2, "parent_id": 3},
    {"id": 4, "name": "Diana Okafor",   "grade_level": 6, "section_id": 2, "parent_id": 4},
    {"id": 5, "name": "Ethan Brown",    "grade_level": 7, "section_id": 3, "parent_id": 5},
]

TEACHERS = [
    {"id": 1, "name": "Ms. Johnson",  "subject": "Math",    "class_ids": [1]},
    {"id": 2, "name": "Mr. Adeyemi",  "subject": "Science", "class_ids": [2]},
    {"id": 3, "name": "Mrs. Chen",    "subject": "English", "class_ids": [3]},
]

CLASSES = [
    {"id": 1, "name": "Grade 5A", "grade_level": 5},
    {"id": 2, "name": "Grade 6A", "grade_level": 6},
    {"id": 3, "name": "Grade 7A", "grade_level": 7},
]

SECTIONS = [
    {"id": 1, "name": "Section A", "class_id": 1, "teacher_id": 1, "capacity": 30, "enrolled_count": 2},
    {"id": 2, "name": "Section B", "class_id": 2, "teacher_id": 2, "capacity": 30, "enrolled_count": 2},
    {"id": 3, "name": "Section C", "class_id": 3, "teacher_id": 3, "capacity": 30, "enrolled_count": 1},
]

def _inject_fault():
    """Fault injection for Labs 1, 6, 8. Used extensively for chaos experiments."""
    if LATENCY_MS > 0:
        time.sleep(LATENCY_MS / 1000.0)
    if FAILURE_RATE > 0 and random.random() < FAILURE_RATE:
        raise HTTPException(status_code=500, detail="Injected academics failure")

@app.get("/health")
def health():
    return {"status": "ok", "service": "academics"}

@app.get("/students")
def list_students():
    _inject_fault()
    return STUDENTS

@app.get("/students/{student_id}")
def get_student(student_id: int):
    _inject_fault()
    for s in STUDENTS:
        if s["id"] == student_id:
            return s
    raise HTTPException(status_code=404, detail="Student not found")

@app.get("/teachers")
def list_teachers():
    _inject_fault()
    return TEACHERS

@app.get("/teachers/{teacher_id}")
def get_teacher(teacher_id: int):
    _inject_fault()
    for t in TEACHERS:
        if t["id"] == teacher_id:
            return t
    raise HTTPException(status_code=404, detail="Teacher not found")

@app.get("/classes")
def list_classes():
    _inject_fault()
    return CLASSES

@app.get("/sections")
def list_sections():
    _inject_fault()
    return SECTIONS

@app.get("/sections/{section_id}")
def get_section(section_id: int):
    _inject_fault()
    for s in SECTIONS:
        if s["id"] == section_id:
            return s
    raise HTTPException(status_code=404, detail="Section not found")