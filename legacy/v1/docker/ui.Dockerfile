FROM python:3.11-slim
WORKDIR /app
COPY requirements/ui.txt requirements/ui.txt
RUN pip install --no-cache-dir -r requirements/ui.txt
COPY ui ui
COPY .streamlit .streamlit
EXPOSE 8501
CMD ["streamlit", "run", "ui/streamlit_app.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
