package server

import (
	"database/sql"
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

type ServerConfig struct {
	Dsn        string  `json:"dsn"`  // Data Source Name for the database connection
	Addr       string  `json:"addr"` // Address to run the server on
	connection *sql.DB // SQL database connection
}

func (cfg *ServerConfig) Initialize() error {
	var err error
	cfg.connection, err = sql.Open("mysql", cfg.Dsn)
	if err != nil {
		return err
	}
	if err = cfg.connection.Ping(); err != nil {
		return err
	}
	return nil
}

func (cfg *ServerConfig) FlagsSet(cmd *cobra.Command) {
	cmd.Flags().StringVar(&cfg.Dsn, "dsn", "", "Database connection string")
	cmd.Flags().StringVar(&cfg.Addr, "addr", ":8080", "Server address to listen on")
	if err := cmd.MarkFlagRequired("dsn"); err != nil {
		fmt.Println("Error marking dsn flag as required:", err)
		os.Exit(1) // Exit if the DSN flag is not set
	}
}
