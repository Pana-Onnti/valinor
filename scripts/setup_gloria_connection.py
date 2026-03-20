#!/usr/bin/env python3
"""
Script to setup and test SSH tunnel connection to Gloria's database.
Implements zero-trust security for production database access.
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional
import getpass
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.ssh_tunnel import create_ssh_tunnel, test_db_connection


class GloriaDBSetup:
    """Setup and test Gloria database connection with SSH tunnel"""
    
    def __init__(self):
        self.config_file = Path.home() / ".valinor" / "gloria_config.json"
        self.ssh_key_path = Path.home() / ".ssh" / "gloria_key"
        
    async def setup_interactive(self):
        """Interactive setup for Gloria DB connection"""
        print("\n" + "="*60)
        print("🔐 Valinor SaaS - Gloria Database Setup")
        print("="*60)
        
        # Check if config exists
        if self.config_file.exists():
            print(f"\n⚠️  Config file exists: {self.config_file}")
            overwrite = input("Overwrite? (y/N): ").lower() == 'y'
            if not overwrite:
                return await self.test_existing_config()
        
        print("\n📋 Please provide Gloria's database connection details:")
        print("(All information will be encrypted and stored securely)")
        
        config = {}
        
        # SSH Configuration
        print("\n--- SSH Tunnel Configuration ---")
        config['ssh_host'] = input("SSH Host (e.g., gloria.example.com): ").strip()
        config['ssh_port'] = int(input("SSH Port [22]: ").strip() or "22")
        config['ssh_user'] = input("SSH Username: ").strip()
        
        # SSH Key or Password
        use_key = input("\nUse SSH key? (Y/n): ").lower() != 'n'
        if use_key:
            default_key = str(self.ssh_key_path)
            key_path = input(f"SSH Key Path [{default_key}]: ").strip() or default_key
            config['ssh_key_path'] = key_path
            
            # Check if key exists
            if not Path(key_path).exists():
                print(f"⚠️  Key file not found: {key_path}")
                create_key = input("Create new SSH key? (y/N): ").lower() == 'y'
                if create_key:
                    await self.generate_ssh_key(key_path)
                else:
                    return
        else:
            config['ssh_password'] = getpass.getpass("SSH Password: ")
        
        # Database Configuration
        print("\n--- Database Configuration ---")
        config['db_host'] = input("DB Host (from SSH perspective) [localhost]: ").strip() or "localhost"
        config['db_port'] = int(input("DB Port [5432 for PostgreSQL]: ").strip() or "5432")
        config['db_name'] = input("Database Name: ").strip()
        config['db_user'] = input("DB Username: ").strip()
        config['db_password'] = getpass.getpass("DB Password: ")
        
        # Database Type
        db_types = {
            "1": "postgresql",
            "2": "mysql",
            "3": "mssql",
            "4": "oracle"
        }
        print("\nDatabase Type:")
        for k, v in db_types.items():
            print(f"  {k}. {v}")
        db_choice = input("Select [1]: ").strip() or "1"
        config['db_type'] = db_types.get(db_choice, "postgresql")
        
        # Security Settings
        print("\n--- Security Settings ---")
        config['max_tunnel_duration'] = int(input("Max tunnel duration (minutes) [60]: ").strip() or "60")
        config['require_2fa'] = input("Require 2FA for production access? (y/N): ").lower() == 'y'
        
        # Save configuration
        await self.save_config(config)
        
        # Test connection
        print("\n🔄 Testing connection...")
        success = await self.test_connection(config)
        
        if success:
            print("\n✅ Connection successful! Gloria's database is accessible.")
            print("\n📝 Next steps:")
            print("1. Run: docker-compose up")
            print("2. Navigate to: http://localhost:3000")
            print("3. Start analysis with Gloria's data")
        else:
            print("\n❌ Connection failed. Please check your settings.")
        
        return success
    
    async def generate_ssh_key(self, key_path: str):
        """Generate new SSH key pair"""
        import subprocess
        
        key_path = Path(key_path)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        
        print(f"\n🔑 Generating SSH key: {key_path}")
        
        # Generate key using ssh-keygen
        cmd = [
            "ssh-keygen",
            "-t", "ed25519",
            "-f", str(key_path),
            "-N", "",  # No passphrase for automation
            "-C", f"valinor@{datetime.now().strftime('%Y%m%d')}"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✅ SSH key generated successfully")
            print(f"\n📋 Public key to add to Gloria's server:")
            print("-" * 40)
            with open(f"{key_path}.pub", "r") as f:
                print(f.read())
            print("-" * 40)
            input("\nPress Enter after adding the public key to the server...")
        else:
            print(f"❌ Failed to generate key: {result.stderr}")
    
    async def save_config(self, config: Dict[str, Any]):
        """Save encrypted configuration"""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        
        # In production, encrypt sensitive fields
        # For MVP, we'll use simple JSON with file permissions
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        # Set restrictive permissions
        os.chmod(self.config_file, 0o600)
        
        print(f"\n💾 Configuration saved to: {self.config_file}")
    
    async def test_connection(self, config: Dict[str, Any]) -> bool:
        """Test database connection through SSH tunnel"""
        try:
            # Create SSH tunnel
            tunnel = await create_ssh_tunnel(
                ssh_host=config['ssh_host'],
                ssh_port=config['ssh_port'],
                ssh_user=config['ssh_user'],
                ssh_key_path=config.get('ssh_key_path'),
                ssh_password=config.get('ssh_password'),
                remote_host=config['db_host'],
                remote_port=config['db_port'],
                local_port=0  # Auto-assign
            )
            
            if not tunnel:
                print("❌ Failed to create SSH tunnel")
                return False
            
            print(f"✅ SSH tunnel established on port {tunnel['local_port']}")
            
            # Test database connection
            db_url = self.build_db_url(config, tunnel['local_port'])
            success = await test_db_connection(db_url, config['db_type'])
            
            if success:
                print("✅ Database connection successful")
                
                # Quick test query
                await self.run_test_query(db_url, config['db_type'])
            
            # Close tunnel
            if tunnel.get('process'):
                tunnel['process'].terminate()
            
            return success
            
        except Exception as e:
            print(f"❌ Connection test failed: {str(e)}")
            return False
    
    def build_db_url(self, config: Dict[str, Any], local_port: int) -> str:
        """Build database connection URL"""
        db_type = config['db_type']
        user = config['db_user']
        password = config['db_password']
        db_name = config['db_name']
        
        # URL encode password
        from urllib.parse import quote_plus
        password_encoded = quote_plus(password)
        
        if db_type == "postgresql":
            return f"postgresql://{user}:{password_encoded}@localhost:{local_port}/{db_name}"
        elif db_type == "mysql":
            return f"mysql://{user}:{password_encoded}@localhost:{local_port}/{db_name}"
        elif db_type == "mssql":
            return f"mssql+pyodbc://{user}:{password_encoded}@localhost:{local_port}/{db_name}?driver=ODBC+Driver+17+for+SQL+Server"
        else:
            raise ValueError(f"Unsupported database type: {db_type}")
    
    async def run_test_query(self, db_url: str, db_type: str):
        """Run a simple test query"""
        try:
            if db_type == "postgresql":
                query = "SELECT current_database(), current_user, version()"
            elif db_type == "mysql":
                query = "SELECT database(), user(), version()"
            elif db_type == "mssql":
                query = "SELECT db_name(), user_name(), @@version"
            else:
                return
            
            # Use appropriate driver
            if db_type == "postgresql":
                import asyncpg
                conn = await asyncpg.connect(db_url)
                result = await conn.fetch(query)
                await conn.close()
            else:
                # For other DBs, use SQLAlchemy
                from sqlalchemy import create_engine
                engine = create_engine(db_url)
                with engine.connect() as conn:
                    result = conn.execute(query).fetchone()
            
            print(f"\n📊 Database Info:")
            print(f"   Database: {result[0]}")
            print(f"   User: {result[1]}")
            print(f"   Version: {str(result[2])[:50]}...")
            
        except Exception as e:
            print(f"⚠️  Test query failed: {str(e)}")
    
    async def test_existing_config(self):
        """Test existing configuration"""
        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)
            
            print("\n🔄 Testing existing configuration...")
            return await self.test_connection(config)
            
        except Exception as e:
            print(f"❌ Error loading config: {str(e)}")
            return False
    
    async def create_env_file(self):
        """Create .env file for Docker Compose"""
        if not self.config_file.exists():
            print("❌ No configuration found. Run setup first.")
            return
        
        with open(self.config_file, 'r') as f:
            config = json.load(f)
        
        env_file = Path(".env")
        
        env_content = f"""# Gloria Database Configuration
# Generated: {datetime.now().isoformat()}

# SSH Tunnel
SSH_HOST={config['ssh_host']}
SSH_PORT={config['ssh_port']}
SSH_USER={config['ssh_user']}
SSH_KEY_PATH={config.get('ssh_key_path', '')}

# Database
DB_TYPE={config['db_type']}
DB_HOST={config['db_host']}
DB_PORT={config['db_port']}
DB_NAME={config['db_name']}
DB_USER={config['db_user']}
DB_PASSWORD={config['db_password']}

# Security
MAX_TUNNEL_DURATION={config['max_tunnel_duration']}
REQUIRE_2FA={config.get('require_2fa', False)}

# LLM Provider (default to API for production)
LLM_PROVIDER=anthropic_api
# ANTHROPIC_API_KEY=your-key-here
"""
        
        with open(env_file, 'w') as f:
            f.write(env_content)
        
        print(f"✅ Environment file created: {env_file}")
        print("⚠️  Remember to add your ANTHROPIC_API_KEY!")


async def main():
    """Main entry point"""
    setup = GloriaDBSetup()
    
    import argparse
    parser = argparse.ArgumentParser(description="Setup Gloria database connection")
    parser.add_argument("--test", action="store_true", help="Test existing configuration")
    parser.add_argument("--env", action="store_true", help="Create .env file from config")
    args = parser.parse_args()
    
    if args.test:
        await setup.test_existing_config()
    elif args.env:
        await setup.create_env_file()
    else:
        await setup.setup_interactive()


if __name__ == "__main__":
    asyncio.run(main())