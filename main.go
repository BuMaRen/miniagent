/*
Copyright © 2025 NAME HERE <EMAIL ADDRESS>
*/
package main

import "lottery/cmd"

func main() {
	command := cmd.NewCommand()
	if err := command.Execute(); err != nil {
		panic(err)
	}
}
