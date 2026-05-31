#!/usr/bin/env python3
"""
Migration script to transfer data from SQLite to PostgreSQL.
"""

import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import Base, engine as postgres_engine
from backend.models import User, Category, Expense, Goal, EmailVerificationCode

# SQLite database path
SQLITE_DB_PATH = Path(__file__).parent / "student_expense.db"
SQLITE_URL = f"sqlite:///{SQLITE_DB_PATH}"

def migrate_data():
    """Migrate all data from SQLite to PostgreSQL."""
    print("Starting migration from SQLite to PostgreSQL...")
    
    # Create SQLite engine
    sqlite_engine = create_engine(SQLITE_URL)
    
    # Create PostgreSQL tables
    print("Creating PostgreSQL tables...")
    Base.metadata.create_all(postgres_engine)
    
    # Migrate users
    print("Migrating users...")
    with Session(sqlite_engine) as sqlite_session, Session(postgres_engine) as pg_session:
        sqlite_users = sqlite_session.query(User).all()
        print(f"  Found {len(sqlite_users)} users in SQLite")
        
        for sqlite_user in sqlite_users:
            # Check if user already exists in PostgreSQL
            existing_user = pg_session.query(User).filter(User.email == sqlite_user.email).first()
            if existing_user:
                print(f"  User {sqlite_user.email} already exists in PostgreSQL, skipping...")
                continue
            
            # Create new user in PostgreSQL
            pg_user = User(
                id=sqlite_user.id,
                name=sqlite_user.name,
                first_name=sqlite_user.first_name,
                last_name=sqlite_user.last_name,
                gender=sqlite_user.gender,
                email=sqlite_user.email,
                password_hash=sqlite_user.password_hash,
                email_verified=sqlite_user.email_verified,
                allowance=sqlite_user.allowance,
            )
            pg_session.add(pg_user)
            pg_session.flush()  # Get the ID
            
            # Migrate user's categories
            print(f"  Migrating categories for user {sqlite_user.email}...")
            sqlite_categories = sqlite_session.query(Category).filter(Category.user_id == sqlite_user.id).all()
            for sqlite_cat in sqlite_categories:
                pg_cat = Category(
                    id=sqlite_cat.id,
                    user_id=pg_user.id,
                    name=sqlite_cat.name,
                    budget=sqlite_cat.budget,
                    color=sqlite_cat.color,
                )
                pg_session.add(pg_cat)
            
            # Migrate user's expenses
            print(f"  Migrating expenses for user {sqlite_user.email}...")
            sqlite_expenses = sqlite_session.query(Expense).filter(Expense.user_id == sqlite_user.id).all()
            for sqlite_exp in sqlite_expenses:
                pg_exp = Expense(
                    id=sqlite_exp.id,
                    user_id=pg_user.id,
                    name=sqlite_exp.name,
                    amount=sqlite_exp.amount,
                    category=sqlite_exp.category,
                    date=sqlite_exp.date,
                )
                pg_session.add(pg_exp)
            
            # Migrate user's goals
            print(f"  Migrating goals for user {sqlite_user.email}...")
            sqlite_goals = sqlite_session.query(Goal).filter(Goal.user_id == sqlite_user.id).all()
            for sqlite_goal in sqlite_goals:
                pg_goal = Goal(
                    id=sqlite_goal.id,
                    user_id=pg_user.id,
                    name=sqlite_goal.name,
                    target=sqlite_goal.target,
                    saved=sqlite_goal.saved,
                )
                pg_session.add(pg_goal)
            
            # Migrate user's email verification codes
            print(f"  Migrating email verification codes for user {sqlite_user.email}...")
            sqlite_codes = sqlite_session.query(EmailVerificationCode).filter(EmailVerificationCode.user_id == sqlite_user.id).all()
            for sqlite_code in sqlite_codes:
                pg_code = EmailVerificationCode(
                    id=sqlite_code.id,
                    user_id=pg_user.id,
                    code_hash=sqlite_code.code_hash,
                    expires_at=sqlite_code.expires_at,
                    attempts=sqlite_code.attempts,
                    used_at=sqlite_code.used_at,
                )
                pg_session.add(pg_code)
        
        pg_session.commit()
        print("Migration completed successfully!")
    
    # Print summary
    with Session(postgres_engine) as pg_session:
        user_count = pg_session.query(User).count()
        category_count = pg_session.query(Category).count()
        expense_count = pg_session.query(Expense).count()
        goal_count = pg_session.query(Goal).count()
        code_count = pg_session.query(EmailVerificationCode).count()
        
        print("\n=== Migration Summary ===")
        print(f"Users: {user_count}")
        print(f"Categories: {category_count}")
        print(f"Expenses: {expense_count}")
        print(f"Goals: {goal_count}")
        print(f"Email Verification Codes: {code_count}")

if __name__ == "__main__":
    if not SQLITE_DB_PATH.exists():
        print(f"Error: SQLite database not found at {SQLITE_DB_PATH}")
        print("Make sure you're running this script from the backend directory.")
        sys.exit(1)
    
    try:
        migrate_data()
    except Exception as e:
        print(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)