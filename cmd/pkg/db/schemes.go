package db

import (
	"database/sql"
	"lottery/pkg/schemas"
)

func CreateSchemesTable(db *sql.DB) error {
	sqlStr := `CREATE TABLE IF NOT EXISTS schemes (
  id INT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(255),
  numbers VARCHAR(255)
)`
	_, err := db.Exec(sqlStr)
	return err
}

func InsertScheme(db *sql.DB, name string, numbers string) error {
	sqlStr := `INSERT INTO schemes (name, numbers) VALUES (?, ?)`
	_, err := db.Exec(sqlStr, name, numbers)
	return err
}

func QuerySchemes(db *sql.DB) ([]schemas.Scheme, error) {
	sqlStr := `SELECT id, name, numbers FROM schemes`
	rows, err := db.Query(sqlStr)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var schemes []schemas.Scheme
	for rows.Next() {
		var id int
		var name, numbers string
		if err := rows.Scan(&id, &name, &numbers); err != nil {
			return nil, err
		}
		scheme := schemas.Scheme{
			Id:      id,
			Name:    name,
			Numbers: numbers,
		}
		schemes = append(schemes, scheme)
	}
	return schemes, nil
}

func DeleteScheme(db *sql.DB, id int) error {
	sqlStr := `DELETE FROM schemes WHERE id = ?`
	_, err := db.Exec(sqlStr, id)
	return err
}
