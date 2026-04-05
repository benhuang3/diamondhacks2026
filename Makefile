.PHONY: help install backend web extension dev clean

help:
	@echo "make install     - install backend + frontend + extension deps"
	@echo "make backend     - run FastAPI backend on :8000"
	@echo "make web         - run Next.js dev server on :3000"
	@echo "make extension   - build Chrome extension to src/frontend/extension/dist"
	@echo "make dev         - run backend + web together (demo mode)"
	@echo "make clean       - remove storefront.db, dist/, .next/"

install:
	python3 -m venv .venv
	.venv/bin/pip install -r src/backend/requirements.txt
	.venv/bin/playwright install chromium
	cd src/frontend/web && npm install
	cd src/frontend/extension && npm install

backend:
	.venv/bin/uvicorn src.backend.main:app --reload --port 8000

web:
	cd src/frontend/web && npm run dev

extension:
	cd src/frontend/extension && npm run build
	@echo "Loaded unpacked: chrome://extensions -> Load unpacked -> src/frontend/extension/dist"

dev:
	@echo "Starting backend (DEMO_MODE) on :8000 and web on :3000"
	@trap 'kill 0' EXIT INT TERM; \
	DEMO_MODE=true .venv/bin/uvicorn src.backend.main:app --reload --port 8000 & \
	cd src/frontend/web && NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev

clean:
	rm -f storefront.db
	rm -rf src/frontend/web/.next
	rm -rf src/frontend/extension/dist
