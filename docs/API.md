# D&D 5e Combat Simulator API Documentation

## Overview

The D&D 5e Combat Simulator provides a RESTful API for managing combat simulations, parties, encounters, and results. All endpoints return JSON responses and use standard HTTP status codes.

## Base URL

- Development: `http://localhost:5000`
- Production: `https://your-app.fly.dev`

## Authentication

Currently, the API uses session-based authentication. All requests should include session cookies.

## Rate Limiting

- General endpoints: 200 requests per day, 50 per hour
- Simulation endpoints: 10 requests per minute
- API endpoints: 100 requests per minute

## Endpoints

### Party Management

#### GET /party
Get available parties for selection.

**Response:**
```json
{
  "parties": [
    {
      "id": 1,
      "name": "Classic Adventurers",
      "description": "A balanced party of classic D&D archetypes.",
      "characters": [
        {
          "name": "Arannis",
          "class": "Wizard",
          "level": 5,
          "summary": "Elven wizard, master of arcane spells."
        }
      ]
    }
  ]
}
```

#### POST /party
Select a party for the current session.

**Request Body:**
```json
{
  "party_id": 1
}
```

**Response:** Redirect to `/encounter`

### Encounter Management

#### GET /encounter
Get encounter selection page.

#### POST /encounter/custom
Create a custom encounter.

**Request Body:**
```json
{
  "monsters": [
    {
      "name": "Goblin",
      "hp": 7,
      "ac": 15,
      "cr": "1/4",
      "ability_scores": {
        "str": 8,
        "dex": 14,
        "con": 10,
        "int": 10,
        "wis": 8,
        "cha": 8
      }
    }
  ],
  "party_level": 5,
  "party_size": 4
}
```

**Response:**
```json
{
  "balance": {
    "base_xp": 50,
    "total_xp": 75,
    "difficulty": "easy",
    "thresholds": [250, 500, 750, 1100]
  },
  "warnings": ["Encounter is balanced."],
  "monsters": [...]
}
```

#### POST /encounter/prebuilt
Select a prebuilt encounter template.

**Request Body:**
```json
{
  "template_name": "Kobold Mob",
  "party_level": 5,
  "party_size": 4
}
```

**Response:**
```json
{
  "balance": {...},
  "warnings": [...],
  "monsters": [...],
  "template": {
    "name": "Kobold Mob",
    "level": 1,
    "type": "mob",
    "monsters": [...]
  }
}
```

### Monster API

#### GET /api/monsters
Get all available monsters.

**Query Parameters:**
- `cr` (optional): Filter by challenge rating (e.g., "1/4", "1", "2")

**Response:**
```json
{
  "monsters": [
    {
      "name": "Goblin",
      "hp": 7,
      "ac": 15,
      "cr": "1/4",
      "ability_scores": {...},
      "actions": [...]
    }
  ]
}
```

#### POST /api/encounter/balance
Check encounter balance without creating an encounter.

**Request Body:**
```json
{
  "monsters": [...],
  "party_level": 5,
  "party_size": 4
}
```

**Response:**
```json
{
  "balance": {
    "base_xp": 50,
    "total_xp": 75,
    "difficulty": "easy",
    "thresholds": [250, 500, 750, 1100]
  },
  "warnings": ["Encounter is balanced."]
}
```

### Simulation

#### GET /simulate
Start a combat simulation.

**Response:** HTML page with simulation interface.

#### GET /simulate/status
Get simulation progress status.

**Response:**
```json
{
  "progress": 75,
  "log": ["-- Round 1 --", "Arannis casts Fireball: 24 damage."],
  "done": false
}
```

#### GET /simulate/results
Get simulation results (redirects to results page).

### Results

#### GET /results
Get simulation results page.

**Query Parameters:**
- `sim_id` (optional): Specific simulation ID

#### GET /results/detailed
Get detailed combat log.

**Query Parameters:**
- `sim_id`: Simulation ID

**Response:**
```json
{
  "log": [
    "-- Round 1 --",
    "Arannis casts Fireball on Goblin: 24 damage.",
    "Goblin attacks Arannis: 5 damage."
  ]
}
```

#### GET /results/statistics
Get combat statistics.

**Query Parameters:**
- `sim_id`: Simulation ID

**Response:**
```json
{
  "statistics": {
    "total_rounds": 3,
    "winner": "party",
    "damage_dealt": 45,
    "damage_taken": 12,
    "spells_cast": 2
  }
}
```

#### GET /results/export
Export simulation results as JSON.

**Query Parameters:**
- `sim_id`: Simulation ID

**Response:**
```json
{
  "simulation": {
    "id": 1,
    "winner": "party",
    "rounds": 3,
    "created_at": "2024-01-01T12:00:00Z"
  },
  "logs": [...],
  "statistics": {...}
}
```

#### GET /history
Get simulation history for current session.

**Response:**
```json
{
  "simulations": [
    {
      "id": 1,
      "party_level": 5,
      "encounter_type": "custom",
      "result": "party",
      "rounds": 3,
      "created_at": "2024-01-01T12:00:00Z"
    }
  ]
}
```

### Health Check

#### GET /healthz
Health check endpoint for monitoring.

**Response:**
```
ok
```

## Error Responses

All endpoints may return the following error responses:

### 400 Bad Request
```json
{
  "error": "Invalid input data: party_level must be an integer",
  "type": "ValidationError"
}
```

### 404 Not Found
```json
{
  "error": "Simulation not found",
  "type": "DatabaseError"
}
```

### 429 Too Many Requests
```json
{
  "error": "Rate limit exceeded",
  "type": "RateLimitError"
}
```

### 500 Internal Server Error
```json
{
  "error": "An unexpected error occurred",
  "type": "Exception"
}
```

## Data Types

### Monster
```json
{
  "name": "string",
  "hp": "integer",
  "ac": "integer",
  "cr": "string",
  "ability_scores": {
    "str": "integer",
    "dex": "integer",
    "con": "integer",
    "int": "integer",
    "wis": "integer",
    "cha": "integer"
  }
}
```

### Character
```json
{
  "name": "string",
  "class": "string",
  "level": "integer",
  "summary": "string"
}
```

### Party
```json
{
  "id": "integer",
  "name": "string",
  "description": "string",
  "characters": ["Character"]
}
```

## Examples

### Complete Workflow

1. **Select Party:**
```bash
curl -X POST http://localhost:5000/party \
  -H "Content-Type: application/json" \
  -d '{"party_id": 1}'
```

2. **Create Custom Encounter:**
```bash
curl -X POST http://localhost:5000/encounter/custom \
  -H "Content-Type: application/json" \
  -d '{
    "monsters": [{"name": "Goblin", "hp": 7, "ac": 15, "cr": "1/4"}],
    "party_level": 5,
    "party_size": 4
  }'
```

3. **Start Simulation:**
```bash
curl http://localhost:5000/simulate
```

4. **Check Status:**
```bash
curl http://localhost:5000/simulate/status
```

5. **Get Results:**
```bash
curl http://localhost:5000/results/statistics?sim_id=1
```

## Rate Limiting Headers

Responses include rate limiting headers:
- `X-RateLimit-Limit`: Request limit per window
- `X-RateLimit-Remaining`: Remaining requests in current window
- `X-RateLimit-Reset`: Time when the rate limit resets

## Security

- All endpoints validate and sanitize input
- CSRF protection enabled for state-changing operations
- Rate limiting prevents abuse
- Security headers included in all responses 