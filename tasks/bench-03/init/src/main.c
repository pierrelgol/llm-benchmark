#include "toml.h"
#include <stdio.h>
#include <stdlib.h>

int	main(int argc, char **argv)
{
	t_toml	*toml;

	if (argc != 2)
	{
		fprintf(stderr, "Usage: %s <file.toml>\n", argv[0]);
		return (EXIT_FAILURE);
	}
	toml = toml_parse(NULL);
	if (!toml)
	{
		fprintf(stderr, "Failed to parse TOML\n");
		return (EXIT_FAILURE);
	}
	toml_free(toml);
	return (EXIT_SUCCESS);
}