from locust import HttpUser, task, between


class SchoolUser(HttpUser):
    """Simulates a student/teacher hitting the school dashboard."""

    wait_time = between(0.5, 1.5)
    host = "http://gateway-stable:3000"

    def on_start(self):
        """Login once per simulated user session to get a JWT."""
        response = self.client.post(
            "/api/auth/login",
            params={
                "email": "admin@school.edu",
                "password": "admin123",
            },
        )
        if response.status_code == 200:
            self.token = response.json().get("access_token")
        else:
            self.token = None

    @task(3)
    def view_dashboard(self):
        """Most common operation — load the aggregated dashboard."""
        self.client.get("/api/dashboard/admin/overview")

    @task(2)
    def list_students(self):
        """View the academics list."""
        self.client.get("/api/academics/students")

    @task(1)
    def check_health(self):
        """Health check."""
        self.client.get("/health")