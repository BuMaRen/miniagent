package db

import (
	"fmt"
	"strings"
	"testing"
)

func TestSQ(t *testing.T) {
	schemasList := []int{1, 2, 3}
	placeholders := strings.Repeat("?,", len(schemasList))
	placeholders = strings.TrimRight(placeholders, ",")
	sqlStr := fmt.Sprintf("SELECT id, username, scheme_name, price, created_at FROM orders WHERE scheme_name IN (%s)", placeholders)
	fmt.Println(sqlStr)
}
