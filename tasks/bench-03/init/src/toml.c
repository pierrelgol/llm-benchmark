#include "toml.h"
#include <stdlib.h>

t_toml	*toml_parse(const char *content)
{
	(void)content;
	return (NULL);
}

void	toml_free(t_toml *root)
{
	free(root);
}