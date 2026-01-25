# sumtyme.ai Dashboard

A real-time cryptocurrency dashboard powered by **sumtyme.ai** CIL (Causal Intelligence Layer) that provides causal analysis of market structure.

## Features

- **Real-time Market Data**: Live candlestick data from Binance WebSocket feeds
- **AI-Powered Predictions**: Integration with sumtyme.ai's API for causal chain analysis
- **Multi-Timeframe Analysis**: Track 1m, 3m, 5m, and 15m intervals simultaneously
- **Propagation Tracking**: Visual indicators showing how directional changes propagate across timeframes for real-time foresight
- **Quad View Mode**: Monitor up to 4 different cryptocurrencies at once
- **Historical Performance**: Toggle between normal and 5x historical data modes
- **Custom Timeframes**: Set any valid Binance timeframe for analysis

Works on desktop devices

## Architecture

### Frontend (React + TypeScript)
- **React 18** with TypeScript
- **Lightweight Charts** for candlestick visualization
- **TailwindCSS** for styling
- **Supabase** for real-time prediction storage
- **Vite** for fast development and building

### Backend (Python FastAPI)
- **FastAPI** web framework
- **Sumtyme.ai EIP Client** for AI predictions
- **Pandas** for data processing
- **Uvicorn** ASGI server

## Prerequisites

### Frontend
- Node.js 16+ and npm/yarn
- A Supabase account (free tier works)

### Backend
- Python 3.9+
- Sumtyme.ai API key (get from [sumtyme.ai](https://docs.sumtyme.ai))
- pip package manager

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/sumteam/projects.git
cd ui-web-app-2
```

### 2. Backend Setup

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install sumtyme package
pip install sumtyme
```

**Configure Sumtyme API Key:**

Edit `sumtyme_server.py` and replace the API key:

```python
eip_client = EIPClient(apikey='YOUR_SUMTYME_API_KEY_HERE')
```

## Running the Application

### 1. Start the Backend Server

```bash
# From backend directory with venv activated
python sumtyme_server.py
```

The backend will start on `http://localhost:8000`

You should see:
```
============================================================
Starting Sumtyme API Wrapper v2.0.0
============================================================
Sumtyme package available: True

Endpoints:
  - POST /forecast/ohlc (NEW)
  - POST /forecast/univariate (NEW)
  - POST /analysis/propagation (NEW)
  - POST /predict/directional_change (LEGACY - Deprecated)
  - GET /health
============================================================
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 2. Start the Frontend Development Server

```bash
# In second command prompt/terminal window
cd ui-web-app-2
npm install
npm run dev
```

The frontend will start on `http://localhost:5173` (or similar)

### 3. Access the Dashboard

Open your browser and navigate to `http://localhost:5173`

## Usage Guide

### Basic Features

1. **View Live Charts**: Charts update automatically with real-time Binance data
2. **Switch Tickers**: Enter any valid Binance ticker (e.g., ETHUSDT, ADAUSDT) in the search box
3. **Toggle Insights**: Click "See All Insights" to show all predictions or only propagations

### Advanced Features

1. **Quad View**: Click "Quad View" to monitor 4 tickers simultaneously
2. **History Mode**: Toggle "History (5x)" to load 5x more historical data for longer analysis
3. **Info Modal**: Click "Info" to view current propagations and system information

### Understanding Predictions

- **Green dots**: Positive causal chains
- **Red dots**: Negative causal chains
- **Labels**: Show timeframe (1m, 3m, 5m, 15m) for each prediction

### Propagations

The system tracks how directional changes propagate from higher to lower frequency timeframes:
- **Propagation ID**: Unique identifier for each trend chain
- **Propagation Level**: Depth of the propagation
- **Change Type**: Positive (green) or Negative (red)

## Configuration

### Backend Configuration

Edit `sumtyme_server.py` to modify:

```python

# Reasoning mode (options: 'proactive', 'reactive')
REASONING_MODE = 'proactive'

# CORS origins
allow_origins=["http://localhost:3000", "http://localhost:5173"]
```

### Frontend Configuration

Edit timeframe configurations in `binanceAPI.ts`:

```typescript
// Modify base data limits
export const calculateDataLimit = (interval: string): number => {
  if (interval === '1m') {
    return 3000;  // Adjust as needed
  }
  // ... other intervals
};
```
NOTE: If you are outside the US, please change the part of the API endpoint containing api.binance.us to api.binance.com.

## API Endpoints

### Backend Endpoints

#### Health Check
```bash
GET /health
```

#### OHLC Forecast (Main Prediction Endpoint)
```bash
POST /forecast/ohlc
Content-Type: application/json

{
  "data_input": [
    {
      "datetime": "2024-01-01 00:00:00",
      "open": 42000.0,
      "high": 42100.0,
      "low": 41900.0,
      "close": 42050.0
    }
    // ... 5000 more historical candles
  ],
  "interval": 1,
  "interval_unit": "minutes",
  "reasoning_mode": "proactive"
}
```

Response:
```json
{
  "causal_chain": 1,  // -1 (bearish), 0 (neutral), or 1 (bullish)
  "timestamp": "2024-01-01 00:01:00",
  "processing_time_ms": 1234.56,
  "data_periods": 5001
}
```

## Troubleshooting

### Backend Issues

**Issue**: `sumtyme package not found`
```bash
# Solution: Install sumtyme package
pip install sumtyme
```

**Issue**: `EIP Client not initialized`
```bash
# Solution: Check your API key in sumtyme_server.py
# Get API key from https://sumtyme.ai
```

**Issue**: `Insufficient data: X periods. Need at least 5001`
```bash
# Solution: The API requires exactly 5001 data points
# Check your data preparation in the frontend
```

### Frontend Issues

**Issue**: Charts not updating
```bash
# Solution: Check that backend is running on http://localhost:8000
# Verify VITE_SUMTYME_API_URL in .env file
```

**Issue**: Supabase connection errors
```bash
# Solution: Verify Supabase credentials in .env
# Check that predictions table exists with correct schema
```

**Issue**: "Invalid ticker" errors
```bash
# Solution: Ensure ticker is valid on Binance.US
# Try common tickers: BTCUSDT, ETHUSDT, ADAUSDT, SOLUSDT
```
**Issue**: Kline data not displaying
```bash
# Solution: Change api.binance.us to api.binance.com if you are outside of the US.
# Try common tickers: BTCUSDT, ETHUSDT, ADAUSDT, SOLUSDT
```
## Performance Optimisation

### Backend
- Predictions are cached to avoid redundant API calls
- Data is paginated when fetching from Supabase
- Async/await used throughout for non-blocking operations

### Frontend
- Kline polling uses mutex to prevent concurrent cycles
- Charts only re-render when necessary
- Prediction data is organized by ticker for efficient lookup

## Security Considerations

1. **API Keys**: Never commit API keys to version control
2. **Environment Variables**: Use `.env` files for sensitive data
3. **CORS**: Restrict origins in production
4. **Rate Limiting**: Implement rate limiting for production deployments
5. **Authentication**: Add user authentication for production use

## Technology Stack

### Frontend
- React 18.3.1
- TypeScript 5.5.3
- TailwindCSS 3.4.15
- Lightweight Charts 4.2.2
- Supabase Client 2.48.1
- Lucide React (icons)
- Vite 5.4.10

### Backend
- Python 3.8+
- FastAPI 0.104.1
- Uvicorn 0.24.0
- Pandas 2.1.3
- Sumtyme AI SDK

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- **sumtyme.ai** for the EIP AI prediction engine
- **Binance** for real-time market data
- **Supabase** for real-time database

## Support

For issues and questions:
- Open an issue on GitHub
- Contact the development team
- Post a bug report on Discord (https://discord.gg/6r2BvXd3)
- Visit sumtyme.ai (https://sumtyme.ai) for API support

## Roadmap

- [ ] Nicer looking frontend
- [ ] Add portfolio tracking
- [ ] Support for more exchanges
- [ ] Mobile app version
- [ ] Advanced charting tools
- [ ] Alert system for predictions
- [ ] Machine learning model explanations (e.g for identifying magnitude)

---

**Note**: This dashboard is for educational and research purposes. Always do your own research before making trading decisions. Cryptocurrency trading carries significant risk.
