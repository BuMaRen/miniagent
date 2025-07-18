/*
Copyright © 2025 NAME HERE <EMAIL ADDRESS>
*/
package cmd

import (
	"lottery/cmd/server"

	"github.com/spf13/cobra"
)

func NewCommand() *cobra.Command {
	cfg := &server.ServerConfig{}
	// rootCmd represents the base command when called without any subcommands
	var rootCmd = &cobra.Command{
		Use:   "lottery",
		Short: "Lottery is a command-line application",
		Long:  `Lottery is a command-line application that allows users to run a lottery server.`,
		// Uncomment the following line if your bare application
		// has an action associated with it:
		Run: func(cmd *cobra.Command, args []string) {
			server.RunServer(cfg)
		},
	}
	rootCmd.SilenceUsage = true
	cfg.FlagsSet(rootCmd)
	return rootCmd
}
