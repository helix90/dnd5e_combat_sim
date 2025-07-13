# D&D 5e Combat Simulator

A comprehensive web-based combat simulator for Dungeons & Dragons 5th Edition, featuring AI-driven combat, party management, encounter building, and detailed analytics.

## 🎯 Features

### Core Combat System
- **Turn-based combat simulation** with initiative tracking
- **AI-driven decision making** for both party and monster actions
- **Spell casting system** with damage calculation and saving throws
- **Combat logging** with detailed round-by-round analysis
- **Multiple victory conditions** and combat end detection

### Party Management
- **Pre-built party templates** (Classic Adventurers, Arcane Strikeforce, etc.)
- **Character customization** with class-specific abilities
- **Level progression** and spell slot management
- **Party composition analysis** and optimization suggestions

### Encounter Building
- **Custom encounter creation** with monster selection
- **Pre-built encounter templates** for quick setup
- **Encounter balance calculation** using D&D 5e guidelines
- **Challenge Rating (CR) filtering** and monster search
- **Encounter difficulty warnings** and recommendations

### API & Integration
- **RESTful API** for programmatic access
- **Open5e API integration** for spell and monster data
- **Local data fallback** when external APIs are unavailable
- **Rate limiting** and security protection
- **Comprehensive API documentation**

### Performance & Monitoring
- **Database query optimization** with indexing and caching
- **Performance monitoring** and metrics collection
- **Error tracking** and alerting system
- **Health check endpoints** for monitoring
- **Load testing** capabilities

### Security & Production Ready
- **Input validation** and sanitization
- **CSRF protection** for all forms
- **Rate limiting** to prevent abuse
- **Security headers** (HSTS, CSP, XSS protection)
- **Non-root Docker containers**
- **Production deployment** with Fly.io

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Docker (optional, for containerized deployment)
- Fly.io CLI (for production deployment)

### Local Development

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd dnd5e_combat_sim
   ```

2. **Set up virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Initialize database**
   ```bash
   python scripts/init_db.py
   ```

5. **Run the application**
   ```bash
   python app.py
   ```

6. **Access the application**
   Open http://localhost:5000 in your browser

### Docker Development

```bash
# Build and run with Docker Compose
docker-compose up --build

# The application will be available at http://localhost:5000
```

## 📖 Usage Guide

### Basic Workflow

1. **Select a Party**
   - Choose from pre-built party templates
   - Each party has different character compositions and strategies

2. **Create an Encounter**
   - Use pre-built encounter templates for quick setup
   - Or create custom encounters by selecting monsters
   - View encounter balance and difficulty warnings

3. **Run Simulation**
   - Start the combat simulation
   - Watch real-time combat progress
   - AI handles all decision-making for both sides

4. **Review Results**
   - Detailed combat log with all actions
   - Statistics and analytics
   - Export results for further analysis

### Advanced Features

#### Custom Encounters
- Filter monsters by Challenge Rating (CR)
- Mix different monster types
- Balance encounters for your party level

#### API Usage
```bash
# Get all monsters
curl http://localhost:5000/api/monsters

# Get monsters by CR
curl http://localhost:5000/api/monsters?cr=1/4

# Check encounter balance
curl -X POST http://localhost:5000/api/encounter/balance \
  -H "Content-Type: application/json" \
  -d '{"monsters": [{"name": "Goblin", "hp": 7, "ac": 15, "cr": "1/4"}], "party_level": 5, "party_size": 4}'
```

## 🏗️ Architecture

### Project Structure
```
dnd5e_combat_sim/
├── app.py                 # Main Flask application
├── models/                # Data models and business logic
│   ├── character.py       # Character class and abilities
│   ├── monster.py         # Monster class and actions
│   ├── combat.py          # Combat simulation engine
│   ├── spells.py          # Spell system and casting
│   └── db.py              # Database management
├── controllers/           # Application controllers
│   ├── encounter_controller.py
│   ├── simulation_controller.py
│   └── results_controller.py
├── utils/                 # Utility modules
│   ├── api_client.py      # External API integration
│   ├── exceptions.py      # Custom exception classes
│   ├── logging.py         # Logging configuration
│   └── monitoring.py      # Performance monitoring
├── data/                  # Static data files
│   ├── parties.json       # Party templates
│   ├── monsters.json      # Monster data
│   └── spells.json        # Spell data
├── templates/             # HTML templates
├── static/                # CSS, JS, and static assets
├── tests/                 # Test suite
├── scripts/               # Deployment and utility scripts
├── docs/                  # Documentation
└── requirements.txt       # Python dependencies
```

### Key Components

#### Combat Engine
- **Initiative System**: Roll-based initiative with tie-breaking
- **Action Resolution**: Attack rolls, saving throws, damage calculation
- **AI Strategy**: Context-aware decision making for both parties
- **State Management**: Efficient combat state tracking and caching

#### Database Layer
- **SQLite**: Lightweight, file-based database
- **Optimized Queries**: Indexed queries for performance
- **Connection Pooling**: Efficient database connection management
- **Migration System**: Schema versioning and updates

#### API Integration
- **Open5e API**: External spell and monster data
- **Fallback System**: Local data when APIs are unavailable
- **Caching**: Response caching for performance
- **Error Handling**: Graceful degradation on API failures

## 🚀 Deployment

### Production Deployment with Fly.io

1. **Install Fly.io CLI**
   ```bash
   # macOS
   brew install flyctl
   
   # Linux
   curl -L https://fly.io/install.sh | sh
   ```

2. **Authenticate and deploy**
   ```bash
   fly auth login
   fly deploy
   ```

3. **Set environment variables**
   ```bash
   fly secrets set SECRET_KEY=your-production-secret-key
   fly secrets set DATABASE_URL=sqlite:////data/app.db
   ```

### Docker Production

```bash
# Build production image
docker build -t dnd5e-combat-sim .

# Run with production settings
docker run -p 5000:5000 -e FLASK_ENV=production dnd5e-combat-sim
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `FLASK_ENV` | Flask environment | `development` |
| `SECRET_KEY` | Flask secret key | `dev-secret-key` |
| `DATABASE_URL` | Database connection | `sqlite:///data/app.db` |
| `PYTHONUNBUFFERED` | Python output buffering | `1` |

## 🧪 Testing

### Run All Tests
```bash
# Unit tests
pytest tests/ -v

# Performance tests
BENCHMARK=1 pytest tests/test_performance.py -v

# Load tests
locust -f tests/test_load.py --host=http://localhost:5000
```

### Test Categories
- **Unit Tests**: Individual component testing
- **Integration Tests**: End-to-end workflow testing
- **Performance Tests**: Response time and throughput testing
- **Load Tests**: Concurrent user simulation
- **Security Tests**: Input validation and security measures

## 📊 Monitoring

### Health Checks
- **Endpoint**: `/healthz`
- **Response**: `ok` with 200 status
- **Monitoring**: 30-second intervals

### Performance Metrics
- **Response Times**: Tracked for all endpoints
- **Error Rates**: Monitored and alerted
- **System Resources**: CPU, memory, disk usage
- **User Analytics**: Privacy-compliant usage statistics

### Logging
- **Application Logs**: Structured logging with levels
- **Error Tracking**: Detailed error context and stack traces
- **Performance Logs**: Slow query and operation tracking
- **Access Logs**: Request/response logging

## 🔧 Development

### Contributing

1. **Fork the repository**
2. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Make your changes**
4. **Add tests** for new functionality
5. **Run the test suite**
   ```bash
   pytest tests/ -v
   ```
6. **Submit a pull request**

### Code Style
- **Python**: PEP 8 compliance
- **Type Hints**: Used throughout the codebase
- **Documentation**: Docstrings for all functions and classes
- **Error Handling**: Comprehensive exception handling

### Development Workflow
```bash
# Set up development environment
source scripts/env_setup.sh

# Run tests
pytest tests/ -v

# Start development server
python app.py

# Run performance benchmarks
BENCHMARK=1 pytest tests/test_performance.py -v
```

## 📚 Documentation

- **[API Documentation](docs/API.md)**: Complete API reference
- **[Deployment Guide](docs/DEPLOYMENT.md)**: Production deployment instructions
- **[User Guide](docs/USER_GUIDE.md)**: End-user documentation
- **[Developer Guide](docs/DEVELOPER_GUIDE.md)**: Development setup and guidelines

## 🤝 Support

### Getting Help
- **Issues**: Report bugs via GitHub issues
- **Discussions**: Use GitHub discussions for questions
- **Documentation**: Check the `docs/` directory
- **Examples**: See `tests/` for usage examples

### Reporting Bugs
When reporting bugs, please include:
- **Environment**: OS, Python version, dependencies
- **Steps to reproduce**: Detailed reproduction steps
- **Expected behavior**: What should happen
- **Actual behavior**: What actually happened
- **Logs**: Relevant error logs and stack traces

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **D&D 5e Rules**: Based on the official D&D 5e ruleset
- **Open5e API**: External data source for spells and monsters
- **Flask**: Web framework for the application
- **Community**: Contributors and testers

## 🎮 Roadmap

### Planned Features
- [ ] **Multiplayer Support**: Real-time collaborative combat
- [ ] **Character Builder**: Visual character creation interface
- [ ] **Campaign Management**: Long-term campaign tracking
- [ ] **Mobile App**: Native mobile application
- [ ] **Advanced AI**: Machine learning for better combat decisions
- [ ] **Mod Support**: Plugin system for custom content

### Performance Improvements
- [ ] **Database Optimization**: Query performance improvements
- [ ] **Caching Layer**: Redis integration for better performance
- [ ] **Async Processing**: Background task processing
- [ ] **CDN Integration**: Static asset optimization

---

**Happy adventuring! 🐉⚔️** 