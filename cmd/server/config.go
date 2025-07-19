package server

import (
	"database/sql"
	"fmt"

	_ "github.com/go-sql-driver/mysql" // MySQL driver for database/sql
	"github.com/spf13/cobra"
	"github.com/stainton/logger"
)

type ServerConfig struct {
	Dsn           string  `json:"dsn"`  // Data Source Name for the database connection
	Addr          string  `json:"addr"` // Address to run the server on
	connection    *sql.DB // SQL database connection
	LoggerOptions *logger.Options
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
	cmd.Flags().StringVar(&cfg.Dsn, "dsn", "", "数据库的连接字串")
	cmd.Flags().StringVar(&cfg.Addr, "addr", ":8080", "服务端监听的地址")
	if err := cmd.MarkFlagRequired("dsn"); err != nil {
		fmt.Println("Error marking dsn flag as required:", err)
	}
}
