import os
import sys
import psycopg2

def load_env():
    """Simple parser to load .env file manually if python-dotenv is not installed."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    val = val.strip().strip('"').strip("'")
                    os.environ[key] = val

def main():
    load_env()
    
    host = os.getenv("POSTGRES_HOST", "192.168.8.82")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "postgres")
    db = os.getenv("POSTGRES_DB", "photo_catalog")
    password = os.getenv("POSTGRES_PASSWORD", "photos")
    
    print("=" * 60)
    print("   PostgreSQL Network Connectivity Verification Script   ")
    print("=" * 60)
    print(f"Target Server : {host}:{port}")
    print(f"Database Name : {db}")
    print(f"Database User : {user}")
    print("-" * 60)
    
    try:
        conn = psycopg2.connect(
            dbname=db,
            user=user,
            password=password,
            host=host,
            port=port,
            connect_timeout=5
        )
        print("SUCCESS: Connection established successfully!")
        
        cur = conn.cursor()
        cur.execute("SELECT version();")
        print(f"Server Version : {cur.fetchone()[0]}")
        
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public';")
        tables = [t[0] for t in cur.fetchall()]
        print(f"Public Tables  : {tables}")
        
        for table in tables:
            cur.execute(f"SELECT COUNT(*) FROM {table};")
            print(f" - Table '{table}' contains {cur.fetchone()[0]} rows")
            
        cur.close()
        conn.close()
        print("-" * 60)
        print("Verification Result: PASSED ⚡")
        print("=" * 60)
        sys.exit(0)
    except Exception as e:
        print("ERROR: Connection failed!")
        print(f"Reason: {e}")
        print("-" * 60)
        print("Verification Result: FAILED ❌")
        print("=" * 60)
        sys.exit(1)

if __name__ == "__main__":
    main()
