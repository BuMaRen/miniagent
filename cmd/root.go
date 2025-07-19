/*
Copyright © 2025 NAME HERE <EMAIL ADDRESS>
*/
package cmd

import (
	"fmt"
	"lottery/cmd/server"

	"github.com/spf13/cobra"
	slog "github.com/stainton/logger"
)

func NewCommand() *cobra.Command {
	cfg := &server.ServerConfig{}
	logOpt := slog.NewLogOptions("lottery")
	// rootCmd represents the base command when called without any subcommands
	var rootCmd = &cobra.Command{
		Use:   "lottery",
		Short: "Lottery is a command-line application",
		Long:  `Lottery is a command-line application that allows users to run a lottery server.`,
		// Uncomment the following line if your bare application
		// has an action associated with it:
		Run: func(cmd *cobra.Command, args []string) {
			cfg.LoggerOptions = logOpt
			server.RunServer(cfg)
			fmt.Println("exit...")
		},
	}
	rootCmd.SilenceUsage = true
	cfg.FlagsSet(rootCmd)
	logOpt.FlagSet(rootCmd)
	return rootCmd
}
