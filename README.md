
# Back in Stock

A back-in-stock notification service that allows customers to subscribe to product availability alerts and receive email notifications when products become available again.

## Features

- Customer subscription form designed to be embedded in an online store.
- Email and SKU validation.
- Duplicate subscription prevention.
- Stock verification through an external stock API.
- Webhook-based restock notifications.
- Email notifications using the Resend API format.
- Webhook event deduplication and notification idempotency.
- Retry handling for failed email deliveries.
- Password-protected administration dashboard.
- Persistent storage using SQLite.

## Tech Stack

- Python 3.13
- FastAPI
- SQLAlchemy
- SQLite
- HTTPX
- Jinja2
- Resend-compatible email API
- Docker

## Project Structure

```text
back-in-stock/
├── main.py
├── database.py
├── models.py
├── schemas.py
├── crud.py
├── services.py
├── requirements.txt
├── Dockerfile
├── .gitignore
└── templates/
    ├── admin.html
    └── embed.html
```

## Environment Variables

Create a `.env` file in the project root:

| Variable | Description |
|---|---|
| `STOCK_API_URL` | Base URL of the store's stock API |
| `STOCK_API_KEY` | API key for stock API authentication |
| `RESEND_API_KEY` | API key for the email service |
| `RESEND_BASE_URL` | Base URL of the Resend-compatible email API |
| `WEBHOOK_SECRET` | Secret used to authenticate incoming stock webhooks |
| `ADMIN_PASSWORD` | Password for the administration dashboard |
| `DATABASE_URL` | SQLAlchemy database connection URL (optional) |

Example:

```env
STOCK_API_URL=http://localhost:3000/api/stock
STOCK_API_KEY=your_stock_api_key
RESEND_API_KEY=your_email_api_key
RESEND_BASE_URL=http://localhost:3000
WEBHOOK_SECRET=your_webhook_secret
ADMIN_PASSWORD=your_admin_password
DATABASE_URL=sqlite:///./back_in_stock.db
```

Do not commit your `.env` file or expose API credentials.

## Running Locally

### 1. Create a virtual environment

```bash
python -m venv .venv
```

### 2. Activate it

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create and populate the `.env` file using the variables listed above.

### 5. Start the application

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

The application will be available at:

- Subscription form: `http://localhost:8000/embed`
- Administration dashboard: `http://localhost:8000/admin`
- API documentation: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

## Running with Docker

### Build the image

```bash
docker build -t back-in-stock .
```

### Run the container

```bash
docker run -d \
  --name back-in-stock \
  -p 8000:8000 \
  --env-file .env \
  -v back-in-stock-data:/app/data \
  back-in-stock
```

The Docker volume preserves the SQLite database when the container is stopped or recreated.

To use a different port, set the `PORT` environment variable and adjust the port mapping accordingly.

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Application information |
| GET | `/health` | Health check |
| GET | `/embed` | Customer subscription form |
| POST | `/api/requests` | Create a subscription |
| POST | `/webhooks/stock` | Process stock update webhooks |
| GET | `/admin` | Protected administration dashboard |

## Testing

The application was tested against the provided challenge harness, including:

- Creating customer subscriptions.
- Preventing duplicate subscriptions.
- Ignoring restock events when the stock API reports that a product is unavailable.
- Processing valid restock events.
- Preventing duplicate webhook processing.
- Handling email delivery failures and subsequent retries.
- Preserving subscription and notification records across application restarts.

## AI Assistance

AI tools were used to assist with implementation planning, debugging, code review, and documentation. The implementation and testing process included reviewing the generated code and validating application behaviour against the provided challenge harness.
