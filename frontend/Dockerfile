FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml
COPY *.py ./
COPY app_pages ./app_pages
COPY components ./components
COPY tours ./tours
COPY .streamlit ./.streamlit
COPY assets ./assets
COPY static ./static
ENV STREAMLIT_SERVER_HEADLESS=true STREAMLIT_SERVER_FILE_WATCHER_TYPE=none
EXPOSE 8501
CMD ["streamlit", "run", "main.py", "--server.address=0.0.0.0", "--server.port=8501"]
