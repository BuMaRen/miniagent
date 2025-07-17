/*
Copyright © 2025 NAME HERE <EMAIL ADDRESS>
*/
package cmd

import (
	"lottery/cmd/server"
	"os"

	"github.com/spf13/cobra"
)

func NewCommand() *cobra.Command {
	cfg := &server.ServerConfig{}
	// rootCmd represents the base command when called without any subcommands
	var rootCmd = &cobra.Command{
		Use:   "lottery",
		Short: "A brief description of your application",
		Long: `A longer description that spans multiple lines and likely contains
examples and usage of using your application. For example:

Cobra is a CLI library for Go that empowers applications.
This application is a tool to generate the needed files
to quickly create a Cobra application.`,
		// Uncomment the following line if your bare application
		// has an action associated with it:
		Run: func(cmd *cobra.Command, args []string) {
			server.RunServer(cfg)
		},
	}
	cfg.FlagsSet(rootCmd)
	return rootCmd
}

// Execute adds all child commands to the root command and sets flags appropriately.
// This is called by main.main(). It only needs to happen once to the rootCmd.
func Execute(cmd *cobra.Command) {
	err := cmd.Execute()
	if err != nil {
		os.Exit(1)
	}
}
